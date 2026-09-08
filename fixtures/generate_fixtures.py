"""
Generates fixtures/fixtures.json: a hand-authored, labeled set of synthetic
PushEvents (matching the real Events API schema, confirmed against GitHub's
docs and a real sample event) covering the actual failure modes Vigil's
two-tier design predicts, not just easy cases:

  - clean_normal              : nothing suspicious anywhere.        TN expected
  - secret_with_suspicious_msg: leaked key + a message that mentions
                                 it -- Tier 1 catches it, Tier 2
                                 confirms it.                        TP expected
  - secret_with_benign_msg    : a REAL leaked key, but the commit
                                 message is completely mundane, so
                                 Tier 1 never selects it for Tier 2
                                 scanning at all.                    FN (a real
                                                                      architectural
                                                                      gap, not a
                                                                      bug)
  - honest_credential_rotation: message says "removing leaked API
                                 key" but the patch genuinely has no
                                 secret left in it (properly fixed) --
                                 Tier 1 flags on the message alone.  FP
  - silent_force_push         : a genuinely diverged ref (real force
                                 push) with a boring message and no
                                 burst -- Tier 1 has no signal for
                                 this at all, so Tier 2's
                                 compare-API check never runs.       FN (another
                                                                      real gap)
  - malicious_burst           : one actor pushing to many distinct
                                 repos in a short window, boring
                                 messages -- Tier 1's burst heuristic
                                 fires.                              TP expected
  - benign_bot_burst          : a legitimate high-volume bot (e.g. a
                                 dependency-update bot) pushing to
                                 many repos quickly -- looks
                                 identical to malicious_burst to the
                                 heuristic.                          FP
"""
import json

def commit(sha, message):
    return {
        "sha": sha,
        "author": {"name": "test-author", "email": "test@example.com"},
        "message": message,
        "distinct": True,
        "url": f"https://api.github.com/repos/octocat/demo/commits/{sha}",
    }


def push_event(event_id, actor, repo, commits, before="0" * 40, head="1" * 40, ts="2026-09-07T12:00:00Z"):
    return {
        "id": event_id,
        "type": "PushEvent",
        "actor": {"login": actor},
        "repo": {"name": repo},
        "payload": {
            "push_id": int(event_id) * 100,
            "size": len(commits),
            "distinct_size": len(commits),
            "ref": "refs/heads/main",
            "head": head,
            "before": before,
            "commits": commits,
        },
        "public": True,
        "created_at": ts,
    }


fixtures = []

# 1. clean_normal
fixtures.append({
    "name": "clean_normal",
    "should_alert": False,
    "event_sequence": [
        push_event("1001", "alice", "alice/blog", [commit("a1" * 20, "fix typo in README")])
    ],
    "compare_result": {"status": "ahead"},
    "commit_patches": {"a1" * 20: "--- a/README.md\n+++ b/README.md\n-helllo\n+hello\n"},
})

# 2. secret_with_suspicious_msg (TP: message flags it, patch confirms real secret)
leaked_patch = (
    "--- a/config.py\n+++ b/config.py\n"
    "-aws_key = ''\n"
    "+aws_access_key_id = 'AKIAABCDEFGHIJKLMNOP'\n"
)
fixtures.append({
    "name": "secret_with_suspicious_msg",
    "should_alert": True,
    "event_sequence": [
        push_event("1002", "bob", "bob/infra", [commit("b2" * 20, "oops committed aws key, removing now")])
    ],
    "compare_result": {"status": "ahead"},
    "commit_patches": {"b2" * 20: leaked_patch},
})

# 3. secret_with_benign_msg (FN: real secret, but Tier 1 never selects it)
fixtures.append({
    "name": "secret_with_benign_msg",
    "should_alert": True,
    "event_sequence": [
        push_event("1003", "carol", "carol/webapp", [commit("c3" * 20, "update deployment config")])
    ],
    "compare_result": {"status": "ahead"},
    "commit_patches": {"c3" * 20: leaked_patch},
})

# 4. honest_credential_rotation (FP: suspicious message, but patch is genuinely clean --
#    demonstrates that Tier 1's message flag always produces an alert in the current
#    design; Tier 2 can only add corroborating evidence, it cannot suppress a Tier 1
#    flag when it finds nothing -- a real limitation, not a bug, documented in the README)
clean_removal_patch = (
    "--- a/config.py\n+++ b/config.py\n"
    "-aws_access_key_id = os.environ['LEGACY_PLACEHOLDER_UNSET']\n"
    "+aws_access_key_id = os.environ['AWS_ACCESS_KEY_ID']\n"
)
fixtures.append({
    "name": "honest_credential_rotation",
    "should_alert": False,
    "event_sequence": [
        push_event("1004", "dave", "dave/tools", [commit("d4" * 20, "remove secret from config, use env var instead")])
    ],
    "compare_result": {"status": "ahead"},
    "commit_patches": {"d4" * 20: clean_removal_patch},
})

# 5. silent_force_push (FN: genuinely diverged ref, but nothing tips off Tier 1)
fixtures.append({
    "name": "silent_force_push",
    "should_alert": True,
    "event_sequence": [
        push_event("1005", "erin", "erin/library", [commit("e5" * 20, "clean up commit history")])
    ],
    "compare_result": {"status": "diverged"},
    "commit_patches": {"e5" * 20: "--- a/lib.py\n+++ b/lib.py\n-old\n+new\n"},
})

# 6. malicious_burst (TP: burst heuristic fires)
burst_actor = "mallory"
burst_events = [
    push_event(str(2000 + i), burst_actor, f"someorg/repo{i}", [commit(f"{i}" * 40, "update")], ts="2026-09-07T12:00:0" + str(i % 10) + "Z")
    for i in range(9)
]
fixtures.append({
    "name": "malicious_burst",
    "should_alert": True,
    "event_sequence": burst_events,
    "compare_result": {"status": "ahead"},
    "commit_patches": {ev["payload"]["commits"][0]["sha"]: "--- a/f\n+++ b/f\n-x\n+y\n" for ev in burst_events},
})

# 7. benign_bot_burst (FP: a legitimate bot's normal behavior looks identical to a burst)
bot_actor = "dependency-update-bot"
bot_events = [
    push_event(str(3000 + i), bot_actor, f"someorg/repo{i}", [commit(f"bb{i}" * 10, "chore: bump dependency versions")], ts="2026-09-07T12:00:0" + str(i % 10) + "Z")
    for i in range(9)
]
fixtures.append({
    "name": "benign_bot_burst",
    "should_alert": False,
    "event_sequence": bot_events,
    "compare_result": {"status": "ahead"},
    "commit_patches": {ev["payload"]["commits"][0]["sha"]: "--- a/package.json\n+++ b/package.json\n-1.0.0\n+1.0.1\n" for ev in bot_events},
})

with open("fixtures/fixtures.json", "w", encoding="utf-8") as f:
    json.dump(fixtures, f, indent=2)

print(f"Wrote {len(fixtures)} fixtures to fixtures/fixtures.json")
for fx in fixtures:
    print(f"  {fx['name']}: should_alert={fx['should_alert']}, events={len(fx['event_sequence'])}")
