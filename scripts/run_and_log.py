"""
Runs a single Vigil polling cycle and appends results to data/alerts.jsonl
and docs/data.json (the dashboard's data source). Designed to be called
repeatedly by a scheduled GitHub Actions workflow (.github/workflows/poll.yml),
which commits the updated files back to the repo -- that's what makes this a
continuously-running, publicly-visible project instead of a script that only
exists when someone happens to run it locally.

Usage:
    python3 scripts/run_and_log.py
"""
import json
import os
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
from tier1 import evaluate as tier1_evaluate, BurstTracker
from tier2 import run as tier2_run, Budget
from poller import _request, fetch_compare, fetch_commit_patch, API_BASE

ALERTS_LOG = "data/alerts.jsonl"
DASHBOARD_DATA = "docs/data.json"
STATE_FILE = "data/poll_state.json"
TIER2_BUDGET = 30
MAX_DASHBOARD_ALERTS = 200  # keep the dashboard file from growing unbounded


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {"etag": None, "seen_ids": [], "total_events_seen": 0, "total_alerts": 0, "cycles_run": 0}


def save_state(state):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    # cap seen_ids so the state file doesn't grow forever
    state["seen_ids"] = state["seen_ids"][-5000:]
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f)


def append_alert(alert):
    os.makedirs(os.path.dirname(ALERTS_LOG), exist_ok=True)
    with open(ALERTS_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(alert) + "\n")


def update_dashboard(state, new_alerts):
    os.makedirs(os.path.dirname(DASHBOARD_DATA), exist_ok=True)
    existing = {"alerts": [], "stats": {}}
    if os.path.exists(DASHBOARD_DATA):
        with open(DASHBOARD_DATA, encoding="utf-8") as f:
            existing = json.load(f)

    all_alerts = existing.get("alerts", []) + new_alerts
    all_alerts = all_alerts[-MAX_DASHBOARD_ALERTS:]

    payload = {
        "alerts": all_alerts,
        "stats": {
            "total_events_seen": state["total_events_seen"],
            "total_alerts": state["total_alerts"],
            "cycles_run": state["cycles_run"],
            "last_updated": datetime.now(timezone.utc).isoformat(),
        },
    }
    with open(DASHBOARD_DATA, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def main():
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        print("ERROR: GITHUB_TOKEN not set.", file=sys.stderr)
        sys.exit(1)

    state = load_state()
    seen_ids = set(state["seen_ids"])
    burst_tracker = BurstTracker()
    budget = Budget(TIER2_BUDGET)

    body, new_etag, poll_interval, rate_remaining = _request(
        f"{API_BASE}/events?per_page=100", token=token, etag=state["etag"]
    )
    state["etag"] = new_etag

    new_alerts = []
    if body:
        now = time.time()
        for event in body:
            if event.get("type") != "PushEvent":
                continue
            if event["id"] in seen_ids:
                continue
            seen_ids.add(event["id"])
            state["total_events_seen"] += 1
            event["_poll_timestamp"] = now

            tier1_result = tier1_evaluate(event, burst_tracker)
            if not tier1_result["flagged"]:
                continue

            alert = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "event_id": event["id"],
                "repo": event.get("repo", {}).get("name"),
                "actor": event.get("actor", {}).get("login"),
                "tier1_reasons": tier1_result["reasons"],
                "tier2_diverged": False,
                "tier2_secret_findings": [],
            }

            if budget.remaining() > 0:
                t2 = tier2_run(
                    event, tier1_result, budget,
                    lambda o, r, b, h: fetch_compare(o, r, b, h, token=token),
                    lambda o, r, s: fetch_commit_patch(o, r, s, token=token),
                )
                alert["tier2_diverged"] = t2["diverged"]
                alert["tier2_secret_findings"] = t2["secret_findings"]

            append_alert(alert)
            new_alerts.append(alert)
            state["total_alerts"] += 1

    state["seen_ids"] = list(seen_ids)
    state["cycles_run"] += 1
    save_state(state)
    update_dashboard(state, new_alerts)

    print(f"Cycle {state['cycles_run']}: rate_limit_remaining={rate_remaining}, "
          f"new_events={len(body) if body else 0}, new_alerts={len(new_alerts)}, "
          f"tier2_calls_used={budget.used}")


if __name__ == "__main__":
    main()
