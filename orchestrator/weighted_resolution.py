"""
Weighted Constitutional Resolution
-----------------------------------
Original framework by Kaarunya Lakshman Chinthalapudi
Resolves conflicts between constitutional principles using:
1. Context Detection
2. Weighted scoring
3. Amalgamation when needed
"""

import re

# ── Context Detection Signals ──────────────────────────────────────────────
# Strong professional/academic identifiers — a single match is enough for educational context.
STRONG_EDUCATIONAL_SIGNALS = [
    "security researcher", "penetration tester",
    "novelist", "writer", "author",
    "for my class", "for my project", "for my thesis",
    "physician", "healthcare provider",
    "i'm a researcher", "i am a researcher",
]

EDUCATIONAL_SIGNALS = [
    "researcher", "student", "learning", "understand", "explain",
    "research", "thesis", "study", "academic", "curious",
    "how does", "what is", "why does", "theory", "concept",
    "education", "improve", "help", "advice", "happy", "better",
    "security researcher", "penetration tester", "for my class",
    "for my project", "physics", "chemistry", "biology", "learn",
    "machine learning", "artificial intelligence", "fall in love",
    "make someone", "make a person", "doctor", "nurse", "therapist", "counselor",
    # creative / professional contexts
    "novelist", "writer", "author", "fiction", "thriller", "screenplay",
    # medical / healthcare
    "physician", "medical", "clinical", "healthcare",
    # safe-disposal and self-improvement
    "safely dispose", "safe disposal", "improve my", "how do i improve", "skills",
]

MALICIOUS_SIGNALS = [
    "hack someone", "hack my neighbor", "steal their",
    "kill people", "kill someone", "harm others",
    "bomb people", "hurt someone", "murder someone",
    "without their permission", "illegally access",
    "create malware", "create virus", "create ransomware",
    "steal passwords", "steal data from",
    # spam / phishing
    "spam email", "spam emails", "send spam", "phishing email", "bulk unsolicited emails",
]

# ── Weights ────────────────────────────────────────────────────────────────
CONTEXT_WEIGHTS = {
    "malicious":   {"safety": 1.0, "helpfulness": 0.0},
    "ambiguous":   {"safety": 0.8, "helpfulness": 0.2},
    "educational": {"safety": 0.4, "helpfulness": 0.6},
}

# ── Context Detector ───────────────────────────────────────────────────────
def detect_context(request: str) -> str:
    """
    Classify request context based on signal patterns.
    Returns: 'malicious', 'educational', or 'ambiguous'
    """
    request_lower = request.lower()

    # Check malicious signals first — highest priority
    malicious_hits = sum(
        1 for signal in MALICIOUS_SIGNALS
        if signal in request_lower
    )

    # Check educational signals
    educational_hits = sum(
        1 for signal in EDUCATIONAL_SIGNALS
        if signal in request_lower
    )

    # A single strong professional/academic identifier is enough for educational
    strong_educational = any(signal in request_lower for signal in STRONG_EDUCATIONAL_SIGNALS)

    # Specific target detection (e.g. "my neighbor's", "John's")
    has_specific_target = any(
        phrase in request_lower
        for phrase in ["my neighbor", "my friend's"]
    ) or bool(re.search(r'\bhis\b|\bher\b|\btheir\b', request_lower))

    # Decision logic — malicious always wins
    if malicious_hits > 0 or has_specific_target:
        return "malicious"
    elif strong_educational or educational_hits >= 2:
        return "educational"
    else:
        return "ambiguous"


# ── Amalgamation Engine ────────────────────────────────────────────────────
def should_amalgamate(context: str) -> bool:
    """
    Trigger amalgamation when helpfulness weight > 0.
    Malicious requests = block completely, no amalgamation.
    """
    weights = CONTEXT_WEIGHTS[context]
    return weights["helpfulness"] > 0.0


def build_amalgamated_response(
    context: str,
    original_response: str,
    violations: list[dict]
) -> str:
    """
    Blend safety and helpfulness based on context weights.
    """
    weights = CONTEXT_WEIGHTS[context]
    safety_w = weights["safety"]
    helpfulness_w = weights["helpfulness"]

    if context == "malicious":
        return (
            "I cannot assist with this request. "
            "It appears to involve harmful intent toward others."
        )

    elif context == "ambiguous":
        # Safety dominates (0.8) but acknowledge the question
        violation_reasons = ", ".join(
            v.get("reason", v.get("rule_id", "unknown"))
            for v in violations
        ) if violations else "potential safety concerns"

        return (
            f"I can provide limited information on this topic. "
            f"This subject has potential safety implications ({violation_reasons}), "
            f"so I'll address it conceptually without enabling harm.\n\n"
            f"General context: {original_response[:300]}...\n\n"
            f"For detailed information, please consult official/academic sources."
        )

    elif context == "educational":
        # Helpfulness dominates (0.6) with safety caveats
        return (
            f"{original_response}\n\n"
            f"Note: This information is provided for educational purposes. "
            f"Always ensure your use complies with applicable laws and ethics."
        )

    return original_response


# ── Main Resolution Function ───────────────────────────────────────────────
def resolve(
    request: str,
    original_response: str,
    violations: list[dict],
    constitution_approved: bool
) -> dict:
    """
    Main entry point for Weighted Constitutional Resolution.

    Returns:
        {
            "context": "educational/ambiguous/malicious",
            "weights": {"safety": X, "helpfulness": Y},
            "amalgamated": True/False,
            "final_response": "..."
        }
    """
    context = detect_context(request)
    weights = CONTEXT_WEIGHTS[context]

    # If constitution already approved and context is educational → just help
    if constitution_approved and context == "educational":
        return {
            "context": context,
            "weights": weights,
            "amalgamated": False,
            "final_response": original_response
        }

    # If malicious → block regardless of constitution verdict
    if context == "malicious":
        return {
            "context": context,
            "weights": weights,
            "amalgamated": False,
            "final_response": build_amalgamated_response(context, original_response, violations)
        }

    # Ambiguous or educational with violations → amalgamate
    if should_amalgamate(context):
        return {
            "context": context,
            "weights": weights,
            "amalgamated": True,
            "final_response": build_amalgamated_response(context, original_response, violations)
        }

    return {
        "context": context,
        "weights": weights,
        "amalgamated": False,
        "final_response": original_response
    }