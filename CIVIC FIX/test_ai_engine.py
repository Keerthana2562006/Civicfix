"""Quick offline regression checks for CivicFix AI; does not touch MySQL."""
from ai_engine import analyze_complaint

CASES = [
    ("Water Supply", "No water has come from taps for four days in our area.", "duration outage should not be Low", 40),
    ("Waterlogging & Drainage", "After rain the street is flooded and water is entering homes.", "homes flooding should be High", 65),
    ("Streetlights", "Live wire is sparking from a lamp post on a dark road.", "live wire should be High", 65),
    ("Roads & Potholes", "A huge pothole near the school caused two near misses today.", "near miss should be High", 65),
    ("Roads & Potholes", "The street light is broken and the whole road is dark.", "conflicting category should request review", None),
    ("Water Supply", "Something is wrong here, please fix it.", "vague complaint should request review", None),
    ("Garbage & Waste", "There is trash trash everywhere and the bin is overflowing.", "repeated words should still identify waste", None),
    ("Unknown", "A strange public issue is happening near the bus stop.", "unknown category should request review", None),
]

print("CivicFix AI regression checks (offline; rule-based expectations, not model accuracy)")
failed = 0
for i, (category, description, label, min_score) in enumerate(CASES, 1):
    result = analyze_complaint(category, description)
    passed = True
    if min_score is not None:
        passed = result["priority_score"] >= min_score
    if "conflicting category" in label or "vague complaint" in label or "unknown category" in label:
        passed = result["review_required"]
    if "identify waste" in label:
        passed = result["department"] == "BBMP Solid Waste"
    failed += not passed
    print(f"{i:02}. {'PASS' if passed else 'CHECK'} | {label} | {result['department']} | {result['priority']} ({result['priority_score']}/100) | review={result['review_required']}")
print(f"\nChecks requiring attention: {failed}/{len(CASES)}")
print("These are targeted behavior checks, not a formal accuracy benchmark.")
