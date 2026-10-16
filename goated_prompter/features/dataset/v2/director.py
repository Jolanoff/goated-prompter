"""The selected Director for a Dataset run."""

from ....presets import get_director_preset


def active_director(data):
    """The selected Director, or None when it has no instructions or does not apply to the target."""
    preset = get_director_preset(data.get("director_preset"))
    if not preset.instructions.strip() or (preset.supported_targets and data.get("target") not in preset.supported_targets):
        return None
    return preset
