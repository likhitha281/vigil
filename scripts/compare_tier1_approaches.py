"""
Direct comparison: for each fixture's commit message, what does the regex
check (tier1.py) say vs. the learned classifier (ml_tier1.py)? Both only see
the message text -- no patch content -- for a fair, apples-to-apples
comparison against the same information budget.

Usage: python3 scripts/compare_tier1_approaches.py
"""
import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
from tier1 import check_message_patterns
from ml_tier1 import predict_message_risk, ml_available

with open("fixtures/fixtures.json", encoding="utf-8") as f:
    fixtures = json.load(f)

if not ml_available():
    print("ML model not found -- run scripts/train_ml_tier1.py first.")
    sys.exit(1)

print(f"{'scenario':<28} {'should_alert':<13} {'regex':<8} {'ml (conf)':<16}")
print("-" * 68)
for fx in fixtures:
    event = fx["event_sequence"][-1]
    commits = event.get("payload", {}).get("commits", [])
    message = commits[0]["message"] if commits else ""

    regex_hit = len(check_message_patterns(event)) > 0
    ml_result = predict_message_risk(message)
    ml_hit, ml_conf = ml_result if ml_result else (None, None)

    print(f"{fx['name']:<28} {str(fx['should_alert']):<13} {str(regex_hit):<8} "
          f"{str(ml_hit) + f' ({ml_conf:.2f})' if ml_result else 'n/a':<16}")
    print(f"  msg: \"{message}\"")
