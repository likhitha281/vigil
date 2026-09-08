"""
Loads the trained TF-IDF + logistic regression model (models/tier1_classifier.joblib)
and exposes a predict function with the same shape as tier1.py's regex check,
so the two can be swapped or compared directly.

This is an OPTIONAL alternative to the regex check in tier1.py, not a
replacement -- see README for the tradeoffs (auditable rules vs. a learned
model trained on synthetic data). Degrades gracefully if the model file or
scikit-learn isn't available.
"""
import os

_pipeline = None
_load_attempted = False

MODEL_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "models", "tier1_classifier.joblib"
)


def ml_available():
    global _pipeline, _load_attempted
    if _load_attempted:
        return _pipeline is not None
    _load_attempted = True
    try:
        import joblib
        if os.path.exists(MODEL_PATH):
            _pipeline = joblib.load(MODEL_PATH)
    except ImportError:
        pass
    return _pipeline is not None


def predict_message_risk(message):
    """
    Returns (is_risky: bool, confidence: float) for a single commit message,
    or None if the model isn't available.
    """
    if not ml_available():
        return None
    proba = _pipeline.predict_proba([message])[0]
    risky_confidence = proba[1]  # class 1 = "risky"
    return (risky_confidence >= 0.5, float(risky_confidence))


def check_message_patterns_ml(event):
    """
    Drop-in alternative to tier1.check_message_patterns, using the learned
    classifier instead of regex. Same return shape: list of (sha, message).
    """
    findings = []
    commits = event.get("payload", {}).get("commits", [])
    for commit in commits:
        message = commit.get("message", "")
        result = predict_message_risk(message)
        if result and result[0]:
            findings.append((commit.get("sha", "?"), message.strip()[:120]))
    return findings
