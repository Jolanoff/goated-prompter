"""The image shape a dataset is made in (the Aspect ratio setting): what it means in words for the scene writer, the
final prompt writer and the quality checks. Auto, or a brief saved before the setting, has no shape."""


def aspect_shape(ratio):
    """(shape, where to spread the people) for a ratio such as "3:4": ("tall", its height), ("wide", its width) or
    ("square", the whole frame); None for Auto or anything that is not two numbers."""
    try:
        width, height = (float(part) for part in str(ratio).split(":"))
    except ValueError:
        return None
    if width <= 0 or height <= 0:
        return None
    if width == height:
        return "square", "the whole frame evenly, since no side is longer"
    return ("wide", "its width, from left to right") if width > height else ("tall", "its height, from top to bottom")


def brief_aspect(brief):
    """The brief's aspect ratio, "Auto" when it has none."""
    return str((brief.get("settings") or {}).get("aspect") or "Auto")


def shape_rule(ratio, template):
    """The template filled with the ratio and its shape; "" for Auto. Placeholders: {ratio}, {shape}, {along}."""
    found = aspect_shape(ratio)
    if not found:
        return ""
    return template.format(ratio=ratio, shape=found[0], along=found[1])
