"""
Generates data/training_messages.json: a larger, more diverse labeled set of
commit messages than the 7 hand-authored fixtures, for training a learned
alternative to the regex-based Tier 1 message check (src/tier1.py).

Honest limitation stated up front: this is SYNTHETIC, templated data, not
real GitHub commit messages. It's useful for demonstrating the ML pipeline
end-to-end and for a controlled comparison against the regex baseline on the
same fixture scenarios, but a production version should be retrained on a
real labeled sample (e.g. pulled from GH Archive) before being trusted.

Two classes:
  risky  - message suggests an ACTIVE problem (a leak just happened, isn't
           necessarily fixed, or otherwise looks concerning)
  benign - message is either unrelated to security, or describes a properly
           completed fix/rotation with no indication anything is still wrong
"""
import json
import random

random.seed(42)

RISKY_TEMPLATES = [
    "oops committed {thing}, removing now",
    "whoops accidentally pushed {thing}",
    "accidentally committed {thing} to the repo",
    "oh no, {thing} got pushed by mistake",
    "sorry, leaked {thing} in last commit",
    "my bad, {thing} was in that diff",
    "fix: {thing} was exposed in config",
    "urgent: remove exposed {thing}",
    "hotfix - {thing} was public in the repo history",
    "revert commit that leaked {thing}",
    "please ignore last commit, has {thing} in it",
    "removing {thing} that got committed by accident",
]

BENIGN_TEMPLATES = [
    "remove {thing}, use environment variable instead",
    "rotate {thing} as part of routine security review",
    "migrate {thing} to secrets manager",
    "update .gitignore to exclude {thing} file going forward",
    "refactor config loading, {thing} now injected at runtime",
    "add documentation for {thing} rotation process",
    "clean up unused {thing} references",
    "bump dependency versions",
    "fix typo in README",
    "update CI pipeline configuration",
    "add unit tests for auth module",
    "improve error handling in api client",
    "refactor database connection pooling",
    "update dependencies to latest versions",
    "fix linting errors across codebase",
    "add logging to background worker",
    "improve test coverage for payments module",
    "merge branch 'feature/new-dashboard'",
    "release v2.3.1",
    "update changelog for this release",
]

THINGS = [
    "api key", "aws key", "secret", "password", "token", "credential",
    "private key", "access key", "auth token", "database password",
    "stripe key", "slack token",
]

EXTRA_BENIGN_UNRELATED = [
    "fix off-by-one error in pagination",
    "add null check before accessing user profile",
    "improve loading spinner animation",
    "refactor sidebar component to use hooks",
    "fix broken link in docs",
    "add retry logic for flaky network calls",
    "update contributor guidelines",
    "fix memory leak in image processing pipeline",
    "add dark mode support",
    "improve accessibility on settings page",
    "fix timezone bug in scheduling logic",
    "add integration tests for checkout flow",
    "clean up dead code in legacy module",
    "update license year",
    "improve build times with better caching",
]


def generate():
    examples = []

    for template in RISKY_TEMPLATES:
        for thing in THINGS:
            examples.append({"message": template.format(thing=thing), "label": "risky"})

    for template in BENIGN_TEMPLATES:
        if "{thing}" in template:
            for thing in THINGS:
                examples.append({"message": template.format(thing=thing), "label": "benign"})
        else:
            examples.append({"message": template, "label": "benign"})

    for msg in EXTRA_BENIGN_UNRELATED:
        examples.append({"message": msg, "label": "benign"})

    random.shuffle(examples)
    return examples


if __name__ == "__main__":
    examples = generate()
    n_risky = sum(1 for e in examples if e["label"] == "risky")
    n_benign = sum(1 for e in examples if e["label"] == "benign")

    with open("data/training_messages.json", "w", encoding="utf-8") as f:
        json.dump(examples, f, indent=2)

    print(f"Wrote {len(examples)} examples to data/training_messages.json "
          f"({n_risky} risky, {n_benign} benign)")
