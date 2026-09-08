"""
Trains a TF-IDF + logistic regression classifier on data/training_messages.json
as a learned alternative to the regex-based suspicious-message check in
src/tier1.py. Saves the trained pipeline to models/tier1_classifier.joblib.

Why this exists: the regex check in tier1.py is a fixed, hand-written list of
patterns -- auditable and predictable, but it can't learn from data or
generalize to phrasings the author didn't think of. This trains a simple,
genuinely learned alternative on the same kind of input (commit message
text only -- no patch content, since that's a Tier 2, budgeted resource) and
evaluates it against the SAME 7 fixture scenarios used for the regex
baseline, for an apples-to-apples comparison.

Honest limitation: training data is synthetic/templated
(scripts/generate_training_data.py), not real GitHub commit messages. This
is useful for demonstrating the pipeline and comparing approaches, not yet
for production use without retraining on real labeled data.

Usage:
    python3 scripts/train_ml_tier1.py
"""
import json
import os

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.model_selection import train_test_split, cross_val_score
import joblib

DATA_PATH = "data/training_messages.json"
MODEL_PATH = "models/tier1_classifier.joblib"


def main():
    with open(DATA_PATH, encoding="utf-8") as f:
        examples = json.load(f)

    X = [e["message"] for e in examples]
    y = [1 if e["label"] == "risky" else 0 for e in examples]

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )

    pipeline = Pipeline([
        ("tfidf", TfidfVectorizer(ngram_range=(1, 2), min_df=1)),
        ("clf", LogisticRegression(max_iter=1000)),
    ])

    cv_scores = cross_val_score(pipeline, X_train, y_train, cv=5, scoring="f1")
    print(f"5-fold CV F1 on training set: {cv_scores.mean():.3f} (+/- {cv_scores.std():.3f})")

    pipeline.fit(X_train, y_train)
    test_score = pipeline.score(X_test, y_test)
    print(f"Held-out test accuracy: {test_score:.3f} ({len(X_test)} examples)")

    os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)
    joblib.dump(pipeline, MODEL_PATH)
    print(f"Saved trained pipeline to {MODEL_PATH}")


if __name__ == "__main__":
    main()
