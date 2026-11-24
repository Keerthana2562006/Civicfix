"""CivicFix hybrid complaint AI: ML-assisted routing and explainable safety rules.

Drop-in API: analyze_complaint(category, description, location="") returns the
fields expected by app.py. This is decision support, not an emergency service.
"""
from pathlib import Path
import re

CATEGORY_DEPARTMENTS = {
    "Garbage & Waste": "BBMP Solid Waste",
    "Roads & Potholes": "BBMP Roads",
    "Streetlights": "BBMP Electrical",
    "Water Supply": "BWSSB Water",
    "Sewerage": "BWSSB Sewerage",
    "Waterlogging & Drainage": "BBMP Storm Water",
}

SIGNALS = {
    "BBMP Solid Waste": ["garbage", "rubbish", "trash", "waste", "dump", "dumping", "litter", "bin overflowing", "overflowing bin", "bad smell", "dead animal", "uncleared waste", "plastic pile", "refuse", "rubbish pile"],
    "BBMP Roads": ["pothole", "road", "footpath", "sidewalk", "pavement", "crater", "broken asphalt", "uneven road", "road cave", "manhole cover missing", "speed breaker", "carriageway"],
    "BBMP Electrical": ["streetlight", "street light", "lamp post", "road light", "dark street", "no lights", "sparking wire", "live wire", "electric pole", "exposed wire", "power cable hanging", "street lamp", "electrical wire"],
    "BWSSB Water": ["water supply", "no water", "water shortage", "tap dry", "dry taps", "water leak", "pipe burst", "drinking water", "low pressure", "contaminated water", "muddy water", "water stopped", "no running water"],
    "BWSSB Sewerage": ["sewage", "sewer", "sewerage", "manhole overflowing", "dirty water flowing", "toilet waste", "drain smell", "septic", "wastewater", "blocked sewer", "raw sewage", "sewage overflow"],
    "BBMP Storm Water": ["waterlogging", "flooded street", "flooding", "storm drain", "rainwater", "drain blocked", "blocked drain", "stagnant water", "street submerged", "rain water", "water on road", "water entering homes", "homes flooded", "flood water", "water inside house"],
}

HIGH_RISK = [
    (r"\b(accidents?|crashes?|injur(?:y|ies|ed)|life.?threatening|near misses?|putting .{0,35} at risk|risk to .{0,35})\b", 35, "possible immediate safety risk"),
    (r"\b(dangerous pothole|pothole.{0,50}(?:accident|rider|two.?wheeler|risk)|two.?wheeler riders? at risk|putting .{0,35} at risk|risk to .{0,35})\b", 25, "dangerous road defect or road-user risk mentioned"),
    (r"\b(school|hospital|clinic|daycare|elderly|wheelchair)\b", 15, "sensitive public facility or vulnerable users mentioned"),
    (r"\b(electric shock|live wire|sparking|electrocution|wire hanging|exposed wire)\b", 40, "electrical hazard mentioned"),
    (r"\b(flood(?:ed|ing)?|water entering homes|water inside (?:the )?house|homes flooded|waist.?deep|submerged|water entering houses)\b", 45, "serious flooding or water entering homes"),
    (r"\b(open manhole|manhole missing|sewage overflow|raw sewage|sewage overflowing)\b", 30, "hazardous open manhole or sewage mentioned"),
    (r"\b(blocked ambulance|ambulance cannot|road completely blocked|fire truck|emergency access)\b", 30, "emergency access may be affected"),
]
MEDIUM_RISK = [
    (r"\b(no water|water supply stopped|water stopped|dry taps|tap is dry)\b.{0,45}\b(for )?(one|two|three|four|five|six|seven|eight|nine|ten|\d+)\s*(days?|weeks?|hours?)\b", 25, "essential water service outage with stated duration"),
    (r"\b(for )?(one|two|three|four|five|six|seven|eight|nine|ten|\d+)\s*(days?|weeks?)\b.{0,45}\b(no water|water supply|water stopped|dry taps)\b", 25, "essential water service outage with stated duration"),
    (r"\b(repeated|again|every day|daily|weeks|months|third time|many times|still not fixed|recurring|long time)\b", 15, "recurring or prolonged service disruption mentioned"),
    (r"\b(leak|broken|blocked|overflow|pothole|dark|damaged|crack|smell|stagnant)\b", 12, "physical fault or service disruption mentioned"),
]

_MODEL = None
_MODEL_TRIED = False

def _load_model():
    global _MODEL, _MODEL_TRIED
    if _MODEL_TRIED:
        return _MODEL
    _MODEL_TRIED = True
    model_path = Path(__file__).resolve().with_name("civicfix_department_model.joblib")
    if model_path.exists():
        try:
            import joblib
            _MODEL = joblib.load(model_path)
        except Exception:
            _MODEL = None
    return _MODEL

def _normalize(value):
    value = (value or "").lower().replace("street lights", "streetlights")
    value = re.sub(r"[^a-z0-9\s/-]", " ", value)
    words = re.sub(r"\s+", " ", value).strip().split()
    collapsed = []
    for word in words:
        if not collapsed or collapsed[-1] != word:
            collapsed.append(word)
    return " ".join(collapsed)

def _rule_scores(text):
    scores = {dept: 0 for dept in SIGNALS}
    matched = {dept: [] for dept in SIGNALS}
    for dept, phrases in SIGNALS.items():
        for phrase in phrases:
            if phrase in text:
                scores[dept] += 2 if " " in phrase else 1
                matched[dept].append(phrase)
    return scores, matched

def analyze_complaint(category, description, location=""):
    category = (category or "").strip()
    desc = _normalize(description)
    text = _normalize(f"{category} {description} {location}")
    evidence_text = _normalize(f"{description} {location}")
    category_dept = CATEGORY_DEPARTMENTS.get(category)
    rule_scores, matches = _rule_scores(evidence_text)
    ranked = sorted(rule_scores.items(), key=lambda item: item[1], reverse=True)
    top_dept, top_score = ranked[0]
    second_score = ranked[1][1]

    model = _load_model()
    model_dept, model_conf = None, 0.0
    if model is not None:
        try:
            model_dept = str(model.predict([text])[0])
            if hasattr(model, "predict_proba"):
                model_conf = float(max(model.predict_proba([text])[0])) * 100
        except Exception:
            model_dept, model_conf = None, 0.0

    text_dept = top_dept if top_score > 0 else None
    conflict = bool(category_dept and text_dept and category_dept != text_dept and top_score >= 2)

    # Core Rule: AI assigns department directly based on category
    if category_dept:
        predicted = category_dept
        confidence = 96.0
        source = "AI (Category-based)"
        if text_dept == category_dept and top_score >= 1:
            confidence = 99.0
            source = "AI (Category + Text Verified)"
        elif conflict:
            confidence = 80.0
            source = "AI (Category-based, Conflicting Text Signals)"
    elif model_dept in CATEGORY_DEPARTMENTS.values() and model_conf >= 65:
        predicted, confidence, source = model_dept, model_conf, "ML model"
    elif text_dept and top_score >= 2:
        predicted = text_dept
        confidence = min(90.0, 55.0 + top_score * 6 + (5 if top_score > second_score else 0))
        source = "Text evidence"
    else:
        predicted, confidence, source = "BBMP Roads", 20.0, "Uncertain fallback"

    vague_patterns = ["something is wrong", "please fix it", "problem here", "not working", "issue is happening", "strange public issue", "help me", "fix this"]
    vague = any(phrase in desc for phrase in vague_patterns) or len(desc.split()) < 3
    review_required = confidence < 55 or not category_dept or conflict or not desc or vague

    reasons = [f"AI assigned department: {predicted} ({source})."]
    if category_dept:
        reasons.append(f"Problem category '{category}' mapped to {category_dept}.")
    if text_dept and text_dept == category_dept:
        reasons.append("Complaint text verified signals: " + ", ".join(matches[text_dept][:5]) + ".")
    elif conflict:
        reasons.append(f"Description mentions '{', '.join(matches[text_dept][:3])}' which may overlap with {text_dept}; admin review recommended.")
    if model_dept:
        reasons.append(f"ML model prediction: {model_dept} ({model_conf:.1f}%).")
    if review_required:
        reasons.append("Manual admin review flagged due to conflicting or vague context.")

    score = 20
    risk_reasons = []
    for pattern, points, label in HIGH_RISK:
        if re.search(pattern, text):
            score += points
            risk_reasons.append(label)
    for pattern, points, label in MEDIUM_RISK:
        if re.search(pattern, text):
            score += points
            risk_reasons.append(label)
    if not risk_reasons:
        risk_reasons.append("No explicit high-risk signal detected; baseline severity applied")
    score = max(0, min(100, score))
    priority = "Critical" if score >= 85 else "High" if score >= 65 else "Medium" if score >= 40 else "Low"
    reasons.append("Priority factors: " + "; ".join(risk_reasons[:5]) + f" (score {score}/100).")

    solution = get_suggested_solution(category, description)

    return {
        "department": predicted,
        "confidence": round(max(0.0, min(100.0, confidence)), 2),
        "priority": priority,
        "priority_score": score,
        "reason": " ".join(reasons),
        "review_required": review_required,
        "assignment_source": source,
        "suggested_solution": solution,
    }


def get_suggested_solution(category, description):
    text = (description or "").lower()
    if any(x in text for x in ["pothole", "crater", "broken road", "footpath", "pavement", "asphalt"]):
        return "Inspect road defect, fill potholes with cold/hot-mix asphalt, compact securely, and level surface."
    if any(x in text for x in ["garbage", "dump", "trash", "waste", "bin overflowing", "litter"]):
        return "Dispatch solid waste collection vehicle, clear garbage accumulation, sanitize area, and monitor bin."
    if any(x in text for x in ["waterlogging", "flooding", "storm drain", "blocked drain", "drain", "rainwater"]):
        return "Desilt and unblock stormwater drain channel, clear obstruction, pump standing rainwater, and ensure free flow."
    if any(x in text for x in ["water supply", "no water", "leak", "pipe burst"]):
        return "Inspect supply valves, identify pipe leak or outage, execute pipeline repair, and restore potable water supply."
    if any(x in text for x in ["streetlight", "dark street", "sparking", "lamp post", "wire hanging"]):
        return "Isolate electrical hazards, repair or replace damaged luminaire/wiring, and verify street lighting operation."
    return "Inspect reported civic defect on-site, verify problem extent, execute standard corrective repairs, and upload completion photo proof."
