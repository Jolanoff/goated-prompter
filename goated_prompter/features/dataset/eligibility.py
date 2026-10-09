"""Authoritative Dataset writer gate: a frozen scene with a PASS self-check."""

from dataclasses import asdict, dataclass

from .scene import validate_self_check


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
    if row.get("scene_status") == "not_generated":
        return SceneEligibility(False, reason="Check this edited scene before enhancement.")
    if not row.get("scene", "").strip():
        return SceneEligibility(False, reason="Build this scene before enhancement.")
    try:
        check = validate_self_check(row.get("self_check", ""), allow_pending=True)
    except ValueError as exc:
        return SceneEligibility(False, reason=str(exc))
    if check != "PASS":
        return SceneEligibility(False, reason=check or "Check this edited scene before enhancement.")
    return SceneEligibility(True)
