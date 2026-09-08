"""
Tier 2: budgeted deep inspection for events Tier 1 already flagged.

Two real GitHub API calls, each with a real cost against the rate limit:
  1. Compare API (GET /repos/{owner}/{repo}/compare/{before}...{head}) -- cheap,
     one call, returns a "status" field. "diverged" is a strong proxy for a
     force-push/history-rewrite, since the Events API itself has no explicit
     "forced" flag (that field only exists in webhook payloads, not polled
     events -- confirmed against GitHub's own docs before building this).
  2. Commit detail API (GET /repos/{owner}/{repo}/commits/{sha}) -- more
     expensive, one call per commit, returns the actual patch/diff text,
     which secret_patterns.scan_text() is run against.

Both fetchers are passed in as arguments (dependency injection) so this
module can be tested deterministically against fixtures without hitting the
real network -- see fixtures/generate_fixtures.py and src/run_fixtures.py.
"""
from secret_patterns import scan_text


class Budget:
    """Tracks how many Tier 2 API calls remain in the current polling cycle."""

    def __init__(self, max_calls):
        self.max_calls = max_calls
        self.used = 0

    def remaining(self):
        return self.max_calls - self.used

    def spend(self, n=1):
        if self.used + n > self.max_calls:
            return False
        self.used += n
        return True


def check_diverged(event, budget, fetch_compare):
    """
    Spend 1 budget unit to call the compare API and check for a diverged
    (force-pushed-looking) ref. fetch_compare(owner, repo, before, head) ->
    dict with a "status" key (real API) or an injected fixture dict.
    Returns (spent: bool, is_diverged: bool).
    """
    if not budget.spend(1):
        return False, False

    repo_name = event.get("repo", {}).get("name", "")
    if "/" not in repo_name:
        return True, False
    owner, repo = repo_name.split("/", 1)
    payload = event.get("payload", {})
    before, head = payload.get("before"), payload.get("head")
    if not before or not head:
        return True, False

    result = fetch_compare(owner, repo, before, head)
    return True, (result.get("status") == "diverged")


def scan_commits_for_secrets(event, commit_shas, budget, fetch_commit_patch):
    """
    Spend up to 1 budget unit per commit fetching its patch and scanning for
    secrets. fetch_commit_patch(owner, repo, sha) -> patch text (real API) or
    an injected fixture string. Returns a list of finding dicts.
    """
    findings = []
    repo_name = event.get("repo", {}).get("name", "")
    if "/" not in repo_name:
        return findings
    owner, repo = repo_name.split("/", 1)

    for sha in commit_shas:
        if not budget.spend(1):
            break
        patch_text = fetch_commit_patch(owner, repo, sha)
        for pattern_name, snippet in scan_text(patch_text):
            findings.append({
                "commit": sha,
                "pattern": pattern_name,
                "snippet": snippet,
            })
    return findings


def run(event, tier1_result, budget, fetch_compare, fetch_commit_patch):
    """
    Full Tier 2 pass for one Tier-1-flagged event. Returns a dict of
    additional findings; safe to call even if the budget is already
    exhausted (everything just no-ops and reports nothing spent).
    """
    result = {"diverged": False, "secret_findings": [], "budget_exhausted": False}

    spent, diverged = check_diverged(event, budget, fetch_compare)
    if not spent:
        result["budget_exhausted"] = True
        return result
    result["diverged"] = diverged

    commits_to_scan = tier1_result.get("commits_of_interest") or [
        c.get("sha") for c in event.get("payload", {}).get("commits", [])
    ]
    result["secret_findings"] = scan_commits_for_secrets(
        event, commits_to_scan, budget, fetch_commit_patch
    )
    if budget.remaining() == 0:
        result["budget_exhausted"] = True
    return result
