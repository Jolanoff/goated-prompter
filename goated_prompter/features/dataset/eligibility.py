"""Authoritative Dataset writer gate: a nonempty scene that has not failed."""

from dataclasses import asdict, dataclass


MAX_CHECK_CHARACTERS = 1200


def validate_self_check(value, *, allow_pending=False):
    if not isinstance(value, str) or len(value) > MAX_CHECK_CHARACTERS:
        raise ValueError("Scene self-check must be compact text.")
    if allow_pending and value == "":
        return value
    if value == "PASS":
        return value
    lines = value.splitlines()
    if (len(lines) != 3 or lines[0] != "REPAIR:" or any(not line.strip() for line in lines[1:])
            or "```" in value):
        raise ValueError("Scene self-check must be PASS or REPAIR with a conflict and a clarification.")
    return "REPAIR:\n" + "\n".join(" ".join(line.split()) for line in lines[1:])


@dataclass(frozen=True)
class SceneEligibility:
    usable: bool
    source_kind: str = "frozen_scene"
    reason: str = None

    def to_dict(self):
        return asdict(self)


def scene_eligibility(row, data):
    if row.get("scene_status") == "failed":
        return SceneEligibility(False, reason=row.get("failure_reason") or "Scene generation failed.")
    if not row.get("scene", "").strip():
        return SceneEligibility(False, reason="Generate an idea for this image before writing its prompt.")
    # Ideas arrive as finished scenes and edits are used as written; only a
    # REPAIR note saved by the former scene check still blocks the writer.
    try:
        check = validate_self_check(row.get("self_check", ""), allow_pending=True)
    except ValueError as exc:
        return SceneEligibility(False, reason=str(exc))
    if check.startswith("REPAIR:"):
        return SceneEligibility(False, reason=check)
    return SceneEligibility(True)
