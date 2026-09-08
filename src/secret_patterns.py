"""
Regex patterns for detecting likely leaked secrets in commit diffs/patches.
Pattern-based, not ML-based -- deliberately simple and auditable, with known
false-positive/false-negative tradeoffs documented in the README.
"""
import re

SECRET_PATTERNS = {
    "aws_access_key_id": re.compile(r"AKIA[0-9A-Z]{16}"),
    "aws_secret_key_assignment": re.compile(
        r"(?i)aws_secret_access_key\s*[:=]\s*['\"]?[A-Za-z0-9/+=]{40}['\"]?"
    ),
    "private_key_header": re.compile(
        r"-----BEGIN ?(RSA|EC|DSA|OPENSSH)? ?PRIVATE KEY-----"
    ),
    "github_pat": re.compile(r"ghp_[A-Za-z0-9]{36}"),
    "github_fine_grained_pat": re.compile(r"github_pat_[A-Za-z0-9_]{22,}"),
    "slack_token": re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),
    "generic_api_key_assignment": re.compile(
        r"(?i)(api[_-]?key|secret|token)\s*[:=]\s*['\"][A-Za-z0-9_\-]{20,}['\"]"
    ),
    "stripe_key": re.compile(r"sk_(live|test)_[A-Za-z0-9]{16,}"),
}


def scan_text(text):
    """Return a list of (pattern_name, matched_snippet) for every match found."""
    findings = []
    for name, pattern in SECRET_PATTERNS.items():
        for match in pattern.finditer(text):
            snippet = match.group(0)
            # redact the middle of the match so we don't print real secrets to logs
            if len(snippet) > 12:
                snippet = snippet[:6] + "..." + snippet[-4:]
            findings.append((name, snippet))
    return findings
