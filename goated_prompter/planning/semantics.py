"""Workflow-independent semantic authority; no concept-to-action database."""

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
