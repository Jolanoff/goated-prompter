"""One Dataset scene-usability decision for writers, actions and UI projections."""

from dataclasses import asdict, dataclass

from .dataset_staging import geometry_errors
from .dataset_visible_content import visible_content_error
from .dataset_staging.rules.framing import framing_intent
from .dataset_scene import validate_self_check


@dataclass(frozen=True)
class SceneEligibility:
    usable: bool
    source_kind: str
    reason: str = None
    warnings: tuple = ()

    def to_dict(self):
        return asdict(self)


def scene_geometry_errors(row, data):
    if "self_check" in row:
        return []  # Compact scenes use their one self-check, not the old geometry evaluator.
    framing_errors = framing_intent(data, row).errors_for(row)
    if row.get("scene_status") == "guided_fallback":
        return framing_errors
    return list(dict.fromkeys([*framing_errors, *geometry_errors(row, dataset_type=data["trigger_type"], require_fields=bool(row.get("geometry")))]))


def scene_eligibility(row, data):
    if "self_check" in row:
        source = "frozen_scene"
        if not row.get("idea", "").strip() or not row.get("scene", "").strip():
            return SceneEligibility(False, source, "Build this scene from its idea first.")
        try:
            check = validate_self_check(row["self_check"], allow_pending=True)
        except ValueError as error:
            return SceneEligibility(False, source, str(error))
        if check != "PASS":
            return SceneEligibility(False, source, check or "Run this scene's compact self-check before writing its prompt.")
        if row.get("scene_status", "valid") != "valid":
            return SceneEligibility(False, source, "Build or repair this scene before writing its prompt.")
        return SceneEligibility(True, source)
    source = "structured_scene" if row.get("geometry") else "manual_prose" if "idea" in row else "legacy_scene"
    if "idea" in row and not row["idea"].strip():
        return SceneEligibility(False, source, "Generate an idea for this item first.")
    if reason := visible_content_error(row.get("idea", "")):
        return SceneEligibility(False, source, reason)
    if not row.get("scene", "").strip() or row.get("scene_status") in {"not_generated", "geometry_warning", "failed"}:
        return SceneEligibility(False, source, "Compose or repair this scene before regenerating its prompt.")
    if reason := visible_content_error(row["scene"]):
        return SceneEligibility(False, source, reason)
    errors = scene_geometry_errors(row, data)
    if errors:
        return SceneEligibility(False, source, errors[0], tuple(errors[1:]))
    warnings = ("Legacy scene has no separate idea; its prose remains authoritative.",) if source == "legacy_scene" else ()
    return SceneEligibility(True, source, warnings=warnings)
