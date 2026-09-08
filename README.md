# Vigil

A budget-constrained risk triage agent for GitHub's public push-event
stream. Vigil polls GitHub's public Events API continuously and flags
`PushEvent`s that look like they leaked a secret, silently rewrote history
(force-push), or came from a burst of suspiciously fast activity across many
repos — while staying inside the API's real rate limits, which is the
actual engineering problem this project is about.

**[Live dashboard](docs/index.html)** — updated every 30 minutes by a
scheduled GitHub Actions workflow. ·
[![tests](../../actions/workflows/test.yml/badge.svg)](../../actions/workflows/test.yml)

## The actual problem: a rate-limited budget, not just detection

GitHub's public Events API is free but constrained: **5,000 requests/hour**
with a token (60/hour without), and GitHub's own docs state the API
**"is not built to serve real-time use cases"** — latency can range from
seconds to hours under load. Two consequences drove the design:

1. **You cannot deeply inspect every event.** Fetching a commit's real diff,
   or checking whether a ref was force-pushed, both cost a real API call.
   At real public-GitHub volume, spending a call on every push exhausts the
   budget almost immediately. So Vigil is two-tiered: **Tier 1** is free
   (metadata already in the polled event); only Tier-1-flagged events get
   to spend from a limited **Tier 2** budget on real API calls.
2. **The Events API has no `forced` field.** That field exists in webhook
   payloads, but not in polled Events API data (verified against GitHub's
   docs before building this, after an earlier wrong assumption on my
   part). The only way to detect a force-push from polled data is the
   Compare API (`status == "diverged"`) — itself a Tier 2 call.

## Four real findings, not hypothetical ones

Running `pytest tests/` or `python3 src/run_fixtures.py` against 7
hand-authored scenarios produces:

```
Precision: 0.50  Recall: 0.50  F1: 0.50
TP=2 FP=2 FN=2 TN=1
```

Every non-obvious outcome is a documented, reproducible limitation, locked
in by `tests/test_fixtures.py` so it can't silently drift:

1. **A real leaked secret with a boring commit message is invisible.**
   (`secret_with_benign_msg`, FN) Tier 1 only reads messages; a secret in a
   commit titled "update deployment config" is never selected for Tier 2
   scanning at all.
2. **Force-pushes are structurally invisible unless something else already
   flagged the event.** (`silent_force_push`, FN) The only force-push
   signal is itself a Tier 2 check, and Tier 2 only runs on Tier-1-flagged
   events — a genuinely diverged ref with a boring message is never
   checked.
3. **Good security hygiene still triggers a false alarm.** (`honest_credential_rotation`, FP) Someone rotates a
   credential and writes an honest commit message about it — Tier 1 flags
   it anyway, and in the rule-based design, Tier 2 can only add evidence,
   never suppress a Tier 1 flag, even when it finds nothing.
4. **A legitimate high-volume bot looks identical to an attack pattern.**
   (`benign_bot_burst`, FP) Dependency-update bots push to many repos
   quickly, indistinguishable from the burst heuristic's intended target
   without a bot allowlist.

## A second, honest experiment: does a learned model do better?

`scripts/compare_tier1_approaches.py` trains a TF-IDF + logistic regression
classifier (`scripts/train_ml_tier1.py`, on **synthetic, templated** data —
stated plainly, not real GitHub messages) and compares it directly against
the regex check, using only the same information (message text, no patch
content) for a fair comparison:

```
scenario                     should_alert  regex    ml (conf)
clean_normal                  False         False    True (0.67)
secret_with_suspicious_msg    True          True     True (0.77)
secret_with_benign_msg        True          False    False (0.33)
honest_credential_rotation    False         True     False (0.36)
silent_force_push             True          False    False (0.37)
malicious_burst               True          False    False (0.29)
benign_bot_burst              False         False    False (0.44)
```

The result is a genuine trade, not a clean win: the learned model **fixes**
finding #3 above (correctly clears `honest_credential_rotation`) but
**introduces a new false positive** on `clean_normal` ("fix typo in
README" scores 0.67 risky, despite a near-identical string appearing in
its own training data as `benign`) — most likely a spurious correlation
picked up from the templated training set rather than a real signal. This
is exactly why the model is kept as a separate, optional comparison
(`src/ml_tier1.py`) rather than swapped into the main pipeline: on this
small, synthetic dataset it isn't clearly better, and knowing *that* is
more useful than assuming a learned model automatically beats a regex.

## Repository layout

```
vigil/
  src/
    secret_patterns.py    # regex patterns for likely leaked secrets
    tier1.py                # free heuristics: message regex, burst detection
    tier2.py                # budgeted: compare API + commit patch secret scan
    ml_tier1.py              # optional learned alternative to tier1's message check
    run_fixtures.py         # deterministic evaluation against fixtures.json
    poller.py                # live agent: real polling loop against api.github.com
  fixtures/
    generate_fixtures.py    # (re)generates fixtures.json
    fixtures.json            # 7 hand-authored, labeled scenarios
  scripts/
    run_and_log.py           # one poll cycle + append to data/, used by the scheduled workflow
    generate_training_data.py # synthetic labeled commit-message dataset
    train_ml_tier1.py        # trains the learned classifier
    compare_tier1_approaches.py # regex vs. ML, side by side
  tests/
    test_fixtures.py         # pytest: per-scenario + confusion-matrix assertions
  docs/
    index.html                # live dashboard (GitHub Pages, served from /docs)
    data.json                  # dashboard's data source, updated by the scheduled workflow
  data/
    alerts.jsonl               # append-only log of every real alert raised
    poll_state.json            # ETag + seen-event-ids, so cycles don't reprocess events
  .github/workflows/
    poll.yml                   # scheduled live polling (every 30 min) + auto-commit
    test.yml                    # CI: runs pytest on every push/PR
```

## How to run

**Deterministic evaluation (no network, no token, no dependencies):**
```bash
python3 src/run_fixtures.py
# or, with pytest for CI-style output:
pip install -r requirements.txt
pytest tests/ -v
```

**Live polling against the real API** (free GitHub token — no paid tier —
from `github.com/settings/tokens`, no scopes needed for public data):
```bash
export GITHUB_TOKEN=ghp_...
python3 src/poller.py --cycles 5 --tier2-budget-per-cycle 20
```

**The learned-model comparison:**
```bash
pip install -r requirements.txt
python3 scripts/generate_training_data.py
python3 scripts/train_ml_tier1.py
python3 scripts/compare_tier1_approaches.py
```

## Deploying your own continuously-running instance

This is what turns Vigil from a script into an actual running system:

1. Push this repo to your own GitHub account.
2. Under **Settings → Pages**, set the source to the `/docs` folder on your
   default branch — this publishes the live dashboard at
   `https://<you>.github.io/<repo>/`.
3. `.github/workflows/poll.yml` runs automatically every 30 minutes using
   the Actions-provided `GITHUB_TOKEN` (no manual secret setup needed) — it
   polls, updates `data/alerts.jsonl` and `docs/data.json`, and commits the
   result back to the repo, which the dashboard then reflects.
4. `.github/workflows/test.yml` runs the test suite on every push, so the
   README's badge reflects real, current CI status.

## Known limitations / next steps

- Reserve a slice of the Tier 2 budget for *randomly sampling* pushes
  independent of Tier 1 flags, to catch silent force-pushes (finding #2).
- Let a clean Tier 2 result downgrade rather than only supplement a Tier 1
  flag (finding #3).
- Add a known-bot allowlist for burst detection (finding #4).
- Retrain the learned classifier on real labeled commit messages (e.g. from
  GH Archive) instead of synthetic templates — the `clean_normal` false
  positive above is a concrete, reproducible motivating example for why
  this matters.
- The regex secret patterns will have both false positives (test/example
  keys) and false negatives (uncovered formats) — not yet measured against
  a corpus of real leaked-secret examples.
