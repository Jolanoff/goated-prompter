"""Output canvas validation and shared image/video composition guidance."""

from math import gcd

RESOLUTION_PRESETS = {
    "1:1": (1024, 1024), "2:3": (768, 1152), "3:2": (1152, 768),
    "3:4": (768, 1024), "4:3": (1024, 768), "9:16": (720, 1280),
    "16:9": (1280, 720), "21:9": (1680, 720),
}
MIN_DIMENSION, MAX_DIMENSION = 16, 16384


def normalize_resolution(value=None, *, draft=False):
    if value is None:
        value = {"aspect_ratio": "Auto"}
    if not isinstance(value, dict) or value.keys() - {"aspect_ratio", "width", "height"}:
        raise ValueError("Resolution must contain aspect_ratio, width and height only.")
    ratio = value.get("aspect_ratio", "Auto")
    if not isinstance(ratio, str) or ratio not in ("Auto", "Custom", *RESOLUTION_PRESETS):
        raise ValueError("Choose a supported aspect ratio or Custom.")
    if ratio != "Custom":
        width, height = RESOLUTION_PRESETS.get(ratio, (1024, 1024))
    else:
        width, height = value.get("width"), value.get("height")
        for dimension in (width, height):
            if draft and dimension == "":
                continue
            low, high = (0, 999999) if draft else (MIN_DIMENSION, MAX_DIMENSION)
            if type(dimension) is not int or not low <= dimension <= high:
                raise ValueError(f"Custom width and height must be whole pixels between {MIN_DIMENSION} and {MAX_DIMENSION}.")
    return {"aspect_ratio": ratio, "width": width, "height": height}


def resolution_catalog():
    return {"presets": {key: {"width": width, "height": height} for key, (width, height) in RESOLUTION_PRESETS.items()},
            "min": MIN_DIMENSION, "max": MAX_DIMENSION}


def resolution_guidance(value=None):
    canvas = normalize_resolution(value)
    if canvas["aspect_ratio"] == "Auto":
        return ""
    width, height = canvas["width"], canvas["height"]
    divisor = gcd(width, height)
    ratio = f"{width // divisor}:{height // divisor}"
    if width == height:
        framing = "Square frame: use balanced subject placement and readable separation without relying on long horizontal or vertical staging."
    elif width > height:
        framing = "Landscape frame: organize horizontal relationships and depth, give subjects breathing room, and avoid clipping heads or full-body subjects against the shallow vertical span."
        if width / height >= 2:
            framing += " This is an ultrawide frame: keep essential action in a readable central region and use the lateral space intentionally rather than inventing extra subjects."
    else:
        framing = "Portrait frame: organize depth or vertical layering, keep the focal subject readable within the narrow width, and avoid cramming side-by-side subjects or cropping important limbs."
    if min(width, height) <= 512 or width * height <= 512 * 512:
        density = "Small output: prioritize clear silhouettes, larger subjects and simple visual hierarchy. Reduce optional background clutter and microscopic texture descriptions; do not rely on tiny text or details that will be unreadable. Preserve required subjects and actions."
    elif width * height >= 2_000_000:
        density = "Large output: allow supported secondary detail and material texture while maintaining a clear focal hierarchy. Extra pixels are not permission to add unrelated subjects or filler."
    else:
        density = "Use moderate scene density and readable focal subjects; secondary details should support the main action."
    return (f"OUTPUT CANVAS — {width} x {height} pixels, aspect ratio {ratio}.\n{framing}\n{density}\n"
            "For video, maintain this framing and edge clearance throughout subject and camera movement. "
            "Honor reference/detail locks and explicit source facts; fit the protected composition rather than silently cropping or removing required content. "
            "Use this canvas to guide visual wording, not as visible text in the image. Do not add unsupported resolution flags or extra JSON keys. "
            "The user sets these dimensions separately in the image/video generator.")
