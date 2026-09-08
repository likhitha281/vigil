"""
Tier 1 heuristics: run on the polled event itself, with zero extra API calls.
This is the "free" filtering pass that decides which events are worth
spending Vigil's rate-limited Tier 2 budget on.

Two checks:
  1. Suspicious commit message patterns (e.g. "remove secret", "oops committed
     key", "revert leaked credentials") -- a leaked secret is very often
     immediately followed by a commit that mentions removing/rotating it.
  2. Burst-push detection: the same actor pushing to an unusually large number
     of distinct repos within a short rolling window -- a pattern consistent
     with a compromised token or automated mass-commit activity, rather than
     a human pushing code.
"""
import re
from collections import defaultdict, deque

SUSPICIOUS_MESSAGE_PATTERNS = [
    re.compile(r"(?i)remove(d)? (the )?(secret|key|credential|password|token)"),
    re.compile(r"(?i)\b(oops|whoops)\b.*(key|secret|credential|password|token)"),
    re.compile(r"(?i)revert.*(leak|credential|secret|key)"),
    re.compile(r"(?i)rotate.*(key|secret|credential)"),
    re.compile(r"(?i)accidentally (committed|pushed|added)"),
]

BURST_WINDOW_SECONDS = 300      # 5-minute rolling window
BURST_DISTINCT_REPO_THRESHOLD = 8  # same actor pushing to >=8 distinct repos in the window


class BurstTracker:
    """Stateful, rolling-window tracker for burst-push detection across a live poll loop."""

    def __init__(self, window_seconds=BURST_WINDOW_SECONDS, threshold=BURST_DISTINCT_REPO_THRESHOLD):
        self.window_seconds = window_seconds
        self.threshold = threshold
        self._history = defaultdict(deque)  # actor -> deque of (timestamp, repo)

    def record_and_check(self, actor, repo, timestamp):
        """Record this push and return True if this actor now looks bursty."""
        history = self._history[actor]
        history.append((timestamp, repo))
        cutoff = timestamp - self.window_seconds
        while history and history[0][0] < cutoff:
            history.popleft()
        distinct_repos = len({r for _, r in history})
        return distinct_repos >= self.threshold


def check_message_patterns(event):
    """Return list of (commit_sha, matched_pattern_description) for suspicious commit messages."""
    findings = []
    commits = event.get("payload", {}).get("commits", [])
    for commit in commits:
        message = commit.get("message", "")
        for pattern in SUSPICIOUS_MESSAGE_PATTERNS:
            if pattern.search(message):
                findings.append((commit.get("sha", "?"), message.strip()[:120]))
                break
    return findings


def evaluate(event, burst_tracker):
    """
    Run all Tier 1 checks on a single PushEvent. Returns a dict:
      {"flagged": bool, "reasons": [str, ...], "commits_of_interest": [sha, ...]}
    """
    reasons = []
    commits_of_interest = []

    message_hits = check_message_patterns(event)
    for sha, message in message_hits:
        reasons.append(f"commit {sha[:8]} message looks like a secret cleanup: \"{message}\"")
        commits_of_interest.append(sha)

    actor = event.get("actor", {}).get("login", "?")
    repo = event.get("repo", {}).get("name", "?")
    timestamp = event.get("_poll_timestamp", 0)
    if burst_tracker.record_and_check(actor, repo, timestamp):
        reasons.append(
            f"actor '{actor}' has pushed to {burst_tracker.threshold}+ distinct repos "
            f"in the last {burst_tracker.window_seconds}s -- possible compromised token / bot burst"
        )

    return {
        "flagged": len(reasons) > 0,
        "reasons": reasons,
        "commits_of_interest": commits_of_interest,
    }
