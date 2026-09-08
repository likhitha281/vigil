"""
pytest suite for Vigil. Wraps the fixture evaluation from src/run_fixtures.py
with per-scenario assertions -- not just a check that the aggregate
precision/recall numbers match, but that each named scenario produces the
specific, individually-meaningful outcome it was designed to demonstrate.

Run with: pytest tests/
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.run_fixtures import run_fixture  # noqa: E402


def _load_fixtures():
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures", "fixtures.json")
    with open(path, encoding="utf-8") as f:
        return {fx["name"]: fx for fx in json.load(f)}


FIXTURES = _load_fixtures()


def test_clean_normal_produces_no_alert():
    result = run_fixture(FIXTURES["clean_normal"])
    assert result["predicted_alert"] is False


def test_secret_with_suspicious_message_is_caught():
    """Tier 1's message check should flag it, and Tier 2 should confirm the real secret."""
    result = run_fixture(FIXTURES["secret_with_suspicious_msg"])
    assert result["predicted_alert"] is True
    assert result["tier2_result"] is not None
    assert len(result["tier2_result"]["secret_findings"]) > 0


def test_secret_with_benign_message_is_missed():
    """
    Documents a real architectural limitation: a genuine leaked secret with a
    mundane commit message is never selected for Tier 2 scanning at all, so
    it goes fully undetected. This test asserts the CURRENT (limited)
    behavior -- if this test starts failing, it means the blind spot has been
    fixed, which is good, and the test (and the README) should be updated.
    """
    result = run_fixture(FIXTURES["secret_with_benign_msg"])
    assert result["predicted_alert"] is False, (
        "If this now passes, the Tier1-gates-Tier2 blind spot has been fixed -- "
        "update this test and the README's documented limitations."
    )


def test_silent_force_push_is_missed():
    """
    Documents the other major architectural limitation: Tier 1 has no direct
    force-push signal, so a genuinely diverged ref with no other red flags is
    invisible end to end.
    """
    result = run_fixture(FIXTURES["silent_force_push"])
    assert result["predicted_alert"] is False, (
        "If this now passes, blind force-push detection has been added -- "
        "update this test and the README's documented limitations."
    )


def test_honest_credential_rotation_still_alerts():
    """
    Documents that Tier 2 can currently only ADD evidence, not suppress a
    Tier 1 flag -- so a message that sounds bad but has a clean patch still
    produces an alert.
    """
    result = run_fixture(FIXTURES["honest_credential_rotation"])
    assert result["predicted_alert"] is True
    assert result["tier2_result"] is not None
    assert len(result["tier2_result"]["secret_findings"]) == 0
    assert result["tier2_result"]["diverged"] is False


def test_malicious_burst_is_caught():
    result = run_fixture(FIXTURES["malicious_burst"])
    assert result["predicted_alert"] is True
    assert any("burst" in r or "distinct repos" in r for r in result["tier1_reasons"])


def test_benign_bot_burst_is_a_false_positive():
    """Documents that burst detection can't yet distinguish a legit bot from a real attack pattern."""
    result = run_fixture(FIXTURES["benign_bot_burst"])
    assert result["predicted_alert"] is True, (
        "If this now passes (no alert), bot-allowlisting has been added -- "
        "update this test and the README's documented limitations."
    )


def test_confusion_matrix_matches_documented_baseline():
    """
    Locks in the exact TP/FP/FN/TN counts documented in the README and
    proposal. A change here should be a deliberate decision (a real
    improvement or regression), not a silent drift -- update the README's
    numbers in the same commit if this legitimately changes.
    """
    results = [run_fixture(fx) for fx in FIXTURES.values()]
    tp = sum(1 for r in results if r["should_alert"] and r["predicted_alert"])
    fp = sum(1 for r in results if not r["should_alert"] and r["predicted_alert"])
    fn = sum(1 for r in results if r["should_alert"] and not r["predicted_alert"])
    tn = sum(1 for r in results if not r["should_alert"] and not r["predicted_alert"])
    assert (tp, fp, fn, tn) == (2, 2, 2, 1)
