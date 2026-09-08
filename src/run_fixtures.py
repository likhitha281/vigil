"""
Runs Vigil's full Tier 1 -> Tier 2 pipeline against fixtures/fixtures.json,
using injected (fake) API responses instead of real network calls, and
scores the result against each fixture's should_alert label.

This is deliberately deterministic and network-free so it can run anywhere,
anytime, with no token and no rate limit -- the live poller (poller.py) is
the separate, real-network counterpart.
"""
import json
import sys
import os

sys.path.insert(0, os.path.dirname(__file__).replace("fixtures", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from tier1 import evaluate as tier1_evaluate, BurstTracker  # noqa: E402
from tier2 import run as tier2_run, Budget  # noqa: E402

TIER2_BUDGET_PER_EVENT = 5  # max Tier 2 API calls spendable per flagged event


def make_fetchers(fixture):
    compare_result = fixture["compare_result"]
    commit_patches = fixture["commit_patches"]

    def fetch_compare(owner, repo, before, head):
        return compare_result

    def fetch_commit_patch(owner, repo, sha):
        return commit_patches.get(sha, "")

    return fetch_compare, fetch_commit_patch


def run_fixture(fixture):
    burst_tracker = BurstTracker()
    # feed every event in the sequence through Tier 1 to build up burst state;
    # only the LAST event in the sequence is scored.
    events = fixture["event_sequence"]
    for i, event in enumerate(events):
        # attach a monotonically increasing poll timestamp for burst tracking
        event["_poll_timestamp"] = 1000 + i
        result = tier1_evaluate(event, burst_tracker)
        if i < len(events) - 1:
            continue  # warm-up event, not scored
        final_event, final_tier1 = event, result

    fetch_compare, fetch_commit_patch = make_fetchers(fixture)
    budget = Budget(TIER2_BUDGET_PER_EVENT)

    tier2_result = None
    if final_tier1["flagged"]:
        tier2_result = tier2_run(final_event, final_tier1, budget, fetch_compare, fetch_commit_patch)

    # Final alert decision: alert if Tier 1 flagged OR Tier 2 found real corroborating evidence.
    predicted_alert = final_tier1["flagged"] or (
        tier2_result is not None and (tier2_result["diverged"] or tier2_result["secret_findings"])
    )

    return {
        "name": fixture["name"],
        "should_alert": fixture["should_alert"],
        "predicted_alert": predicted_alert,
        "tier1_reasons": final_tier1["reasons"],
        "tier2_result": tier2_result,
    }


def main():
    with open("fixtures/fixtures.json", encoding="utf-8") as f:
        fixtures = json.load(f)

    results = []
    for fixture in fixtures:
        results.append(run_fixture(fixture))

    tp = sum(1 for r in results if r["should_alert"] and r["predicted_alert"])
    fp = sum(1 for r in results if not r["should_alert"] and r["predicted_alert"])
    fn = sum(1 for r in results if r["should_alert"] and not r["predicted_alert"])
    tn = sum(1 for r in results if not r["should_alert"] and not r["predicted_alert"])

    precision = tp / (tp + fp) if (tp + fp) else float("nan")
    recall = tp / (tp + fn) if (tp + fn) else float("nan")
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) and precision == precision and recall == recall else float("nan")

    print(f"Vigil fixture evaluation ({len(results)} fixtures)")
    print(f"  Precision: {precision:.2f}  Recall: {recall:.2f}  F1: {f1:.2f}")
    print(f"  TP={tp} FP={fp} FN={fn} TN={tn}\n")

    for r in results:
        outcome = (
            "TP" if r["should_alert"] and r["predicted_alert"] else
            "FP" if not r["should_alert"] and r["predicted_alert"] else
            "FN" if r["should_alert"] and not r["predicted_alert"] else
            "TN"
        )
        print(f"  [{outcome}] {r['name']}")
        for reason in r["tier1_reasons"]:
            print(f"      tier1: {reason}")
        if r["tier2_result"]:
            t2 = r["tier2_result"]
            if t2["diverged"]:
                print(f"      tier2: compare API reports diverged ref (force-push proxy)")
            for finding in t2["secret_findings"]:
                print(f"      tier2: secret pattern '{finding['pattern']}' in commit {finding['commit'][:8]} ({finding['snippet']})")
            if t2["budget_exhausted"]:
                print(f"      tier2: budget exhausted before all checks completed")


if __name__ == "__main__":
    main()
