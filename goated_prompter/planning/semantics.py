"""Workflow-independent semantic authority; no concept-to-action database."""

import re


def support_requirements(source):
    """Conservative lexical projection of explicit support compounds.

    Anchors are arbitrary source words, not anatomical categories. Ambiguous,
    conditional, alternative and quoted clauses remain in the original source;
    they are not turned into unconditional support locks.
    """
    from .rule_compiler import QUOTED
    source = str(source or "")
    masked = re.sub(r"<d>.*?</d>", lambda match: " " * len(match[0]), source, flags=re.S)
    masked = QUOTED.sub(lambda match: " " * len(match[0]), masked)
    normalized = masked.replace("–", "-").replace("—", "-").replace("‑", "-")
    quantities = {"one": 1, "single": 1, "two": 2, "both": 2}
    patterns = (
        (re.compile(r"(?<![\w-])(?P<anchor>\w+)-supported\b", re.I), "external_contact"),
        (re.compile(r"\b(?P<count>one|single|two|both|[1-9]\d?)-(?P<anchor>\w+)\s+(?:\w+\s+){0,3}balance\b", re.I), "balance_support"),
    )
    requirements = []
    for pattern, role in patterns:
        for match in pattern.finditer(normalized):
            start = max(normalized.rfind(mark, 0, match.start()) for mark in (",", ";", ".", "\n")) + 1
            end = min((position for mark in (",", ";", ".", "\n")
                       if (position := normalized.find(mark, match.end())) >= 0), default=len(normalized))
            clause = normalized[start:end]
            if re.search(r"\b(?:no|not|without|avoid|never|if|unless|except|either|or|may|might|could)\b", clause, re.I):
                continue
            requirement = {"source_quote": source[match.start():match.end()],
                           "contact_anchor": match["anchor"].casefold(), "role": role}
            if role == "balance_support":
                raw_count = match["count"].casefold()
                requirement["contact_count"] = quantities[raw_count] if raw_count in quantities else int(raw_count)
            requirements.append(requirement)
    return requirements

DOMAIN_UNDERSTANDING = """DOMAIN / CONCEPT UNDERSTANDING
Before generating ideas, understand the domain, activity, role or world implied by
the user's specific concept. Infer the relevant behaviors, interactions, physical
activities, situations, objects, roles and states dynamically from that concept.
For a profession, sport, performance, environment, event, role, subculture or
specialized activity, show understanding of what subjects in that domain actually
do. Prefer concept-specific activity over generic posing when meaningful activity
is naturally available. Never rely on a fixed menu of examples or scene templates.
Concept fidelity, explicit constraints and authoritative guided inputs win."""

ACTION_MECHANICS = """DYNAMIC UNDERSTANDING / ACTION-FIRST PLANNING
Understand the requested domain/activity and what the subjects actually do.
Infer mechanics dynamically, not from a fixed menu of activities.
Action > pose mechanics > interaction > visibility > camera.
Camera must support the action, never simplify the action to fit a convenient view.
For complex poses describe only defining mechanics: support/contact, load-bearing
limb, relevant arm/leg placement, torso bend/twist, balance, equipment relation,
body-to-object/subject contact, head direction and important visible limbs.
Resolve each participant's role/contact separately; do not impose one global pose.
Keep world/gravity directions distinct from camera-plane directions. Check that
limb orientation, support/contact and weight-bearing claims are compatible at the
same instant. Preserve the user's idea; mark uncertain mechanics rather than
inventing a convenient support that changes the requested action."""
