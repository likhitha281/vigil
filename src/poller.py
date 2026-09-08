"""
Vigil live poller: the real-network counterpart to run_fixtures.py.

Continuously polls GitHub's public events API, respecting the X-Poll-Interval
header and using ETag for conditional requests (so re-polling with no new
events costs nothing against the rate limit). Runs every PushEvent through
Tier 1, and for flagged events, spends from a per-cycle Tier 2 budget on the
real compare API and commit API.

Usage:
    export GITHUB_TOKEN=ghp_...   # free, from github.com/settings/tokens
    python3 src/poller.py [--cycles N] [--tier2-budget-per-cycle N]

Without GITHUB_TOKEN, this still runs but against the much lower 60/hour
unauthenticated rate limit -- fine for a very short demo, not for sustained
polling.
"""
import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.error

from tier1 import evaluate as tier1_evaluate, BurstTracker
from tier2 import run as tier2_run, Budget

API_BASE = "https://api.github.com"
USER_AGENT = "vigil-capstone-project (educational use)"


def _request(url, token=None, etag=None):
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": USER_AGENT,
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if etag:
        headers["If-None-Match"] = etag
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            new_etag = resp.headers.get("ETag")
            poll_interval = int(resp.headers.get("X-Poll-Interval", "60"))
            rate_remaining = resp.headers.get("X-RateLimit-Remaining")
            return body, new_etag, poll_interval, rate_remaining
    except urllib.error.HTTPError as e:
        if e.code == 304:
            return None, etag, 60, e.headers.get("X-RateLimit-Remaining")
        raise


def fetch_compare(owner, repo, before, head, token=None):
    url = f"{API_BASE}/repos/{owner}/{repo}/compare/{before}...{head}"
    body, _, _, _ = _request(url, token=token)
    return body or {}


def fetch_commit_patch(owner, repo, sha, token=None):
    url = f"{API_BASE}/repos/{owner}/{repo}/commits/{sha}"
    body, _, _, _ = _request(url, token=token)
    if not body:
        return ""
    files = body.get("files", [])
    return "\n".join(f.get("patch", "") for f in files if f.get("patch"))


def poll_once(token, etag, burst_tracker, tier2_budget_per_cycle, seen_ids):
    body, new_etag, poll_interval, rate_remaining = _request(
        f"{API_BASE}/events?per_page=100", token=token, etag=etag
    )
    alerts = []
    if body is None:
        return new_etag, poll_interval, rate_remaining, alerts

    now = time.time()
    for event in body:
        if event.get("type") != "PushEvent":
            continue
        if event["id"] in seen_ids:
            continue
        seen_ids.add(event["id"])
        event["_poll_timestamp"] = now

        tier1_result = tier1_evaluate(event, burst_tracker)
        if not tier1_result["flagged"]:
            continue

        alert = {
            "event_id": event["id"],
            "repo": event.get("repo", {}).get("name"),
            "actor": event.get("actor", {}).get("login"),
            "tier1_reasons": tier1_result["reasons"],
            "tier2": None,
        }

        if tier2_budget_per_cycle.remaining() > 0:
            t2 = tier2_run(
                event, tier1_result, tier2_budget_per_cycle,
                lambda o, r, b, h: fetch_compare(o, r, b, h, token=token),
                lambda o, r, s: fetch_commit_patch(o, r, s, token=token),
            )
            alert["tier2"] = t2

        alerts.append(alert)

    return new_etag, poll_interval, rate_remaining, alerts


def main():
    parser = argparse.ArgumentParser(description="Vigil: live GitHub push-event risk triage")
    parser.add_argument("--cycles", type=int, default=5, help="Number of polling cycles to run before exiting")
    parser.add_argument("--tier2-budget-per-cycle", type=int, default=20, help="Max Tier 2 API calls per polling cycle")
    args = parser.parse_args()

    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        print("WARNING: GITHUB_TOKEN not set -- running against the 60/hour unauthenticated "
              "rate limit. Get a free token at https://github.com/settings/tokens and "
              "export GITHUB_TOKEN=... for real sustained polling.", file=sys.stderr)

    etag = None
    seen_ids = set()
    burst_tracker = BurstTracker()

    for cycle in range(args.cycles):
        budget = Budget(args.tier2_budget_per_cycle)
        try:
            etag, poll_interval, rate_remaining, alerts = poll_once(
                token, etag, burst_tracker, budget, seen_ids
            )
        except urllib.error.HTTPError as e:
            print(f"Cycle {cycle}: HTTP error {e.code} -- {e.read().decode('utf-8', errors='replace')[:200]}")
            time.sleep(60)
            continue

        print(f"Cycle {cycle}: rate_limit_remaining={rate_remaining}, "
              f"tier2_calls_used={budget.used}/{budget.max_calls}, alerts={len(alerts)}")
        for alert in alerts:
            print(f"  ALERT repo={alert['repo']} actor={alert['actor']}")
            for reason in alert["tier1_reasons"]:
                print(f"    tier1: {reason}")
            if alert["tier2"]:
                t2 = alert["tier2"]
                if t2["diverged"]:
                    print(f"    tier2: compare API reports diverged ref (force-push proxy)")
                for finding in t2["secret_findings"]:
                    print(f"    tier2: secret pattern '{finding['pattern']}' in commit {finding['commit'][:8]}")

        if cycle < args.cycles - 1:
            time.sleep(poll_interval)


if __name__ == "__main__":
    main()
