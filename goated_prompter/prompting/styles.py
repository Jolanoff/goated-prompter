"""Visual style text for the selected Style option.

Three layers write a prompt and none overrides another: the target model owns how the prompt is written (format,
syntax, order, length), the Style owns the medium and rendering (and, for Realistic, how the image was captured), and
the Director owns what is emphasized inside them.
"""

from ..options.styles import MODE_STYLES, OFF_STYLE, UNSUPPORTED_STYLES
from ..options.targets import canonical_target

STYLE_ADAPTERS = {
    "Anime": "Anime readable silhouettes and intentional line weight; expressive faces with clear eye "
             "shape, iris highlights and readable brows and mouth; anime proportions kept consistent; hair as designed "
             "masses with strand groups; clothing with clear construction and folds in cel or soft shading; light and "
             "color through cel shading, soft gradients, rim light and colored light, with a vivid designed palette. "
             "Do not use photographic camera, lens, skin-pore or film-grain language.",
    "Realistic": "Photorealistic image of a real moment, recorded by one camera, and every visual detail agrees with "
                 "how it was captured. Light is physical: say where it comes from, how hard or soft it is, what it "
                 "falls on, where the shadows land and how skin, fabric and surfaces reflect it. Show the imperfections "
                 "a camera records in this scene, chosen for it rather than from a stock list: skin texture, stray "
                 "hair, fabric that creases and pulls under tension, wear on surfaces. No praise or quality words; "
                 "every word stays photographic.",
    "Illustration": "Stylized 2D illustration: deliberate linework or shapes, a designed color palette and "
                    "non-photographic rendering suited to the subject.",
    "3D render": "3D rendered image: modeled forms, physically based materials, render-style lighting and a clean "
                 "computer-graphics finish.",
    "Product": "Commercial product photography: crisp, controlled rendering of materials with defined reflections "
               "and highlights and a polished advertising finish.",
    "Painting": "Painting: visible brushwork, painterly color mixing and the texture of a traditional medium "
                "(oil, watercolor or gouache, whichever fits the idea).",
}

CAPTURE_ADAPTERS = {
    "Auto": "Capture: choose one capture that fits this image, a dedicated camera with a concrete lens, focal length "
            "and aperture, analog film or a casual phone photo, and name it.",
    "Pro camera": "Capture: a dedicated camera. Name a lens type, focal length and aperture that suit the shot, with "
                  "the matching depth of field, focus placement and clean exposure.",
    "Phone snapshot": "Capture: a casual phone photo. Handheld framing, the phone's wide perspective, computational "
                      "exposure with restrained HDR, slight sensor noise and sharpening, and the light exactly as the "
                      "scene has it; no shallow-focus lens look. Do not name a phone model.",
    "Analog film": "Capture: analog film. Film color response, grain, highlight roll-off and shadow density that suit "
                   "the light and the era, with restrained fading and halation and the lens character of the period; "
                   "never a clean digital look.",
}


def resolve_style(style, target=None, mode=None):
    """Return the effective style name. Auto lets the request decide, except that a Mode whose task is a medium
    (MODE_STYLES) sets it and Anima is anime-native; a style the target cannot render (Realistic on Anima) falls back
    the same way."""
    target = canonical_target(target)
    if style == OFF_STYLE:
        return OFF_STYLE  # something else carries the style; not even Anima's default applies
    if style not in STYLE_ADAPTERS:
        style = MODE_STYLES.get(mode, style)
    if style in STYLE_ADAPTERS and style not in UNSUPPORTED_STYLES.get(target, ()):
        return style
    return "Anime" if target == "Anima" else "Auto"


def style_section(style, target=None, capture="Auto", mode=None):
    """Return the prompt section for the effective style, or an empty string for Auto."""
    resolved = resolve_style(style, target, mode)
    if resolved in ("Auto", OFF_STYLE):
        return ""
    text = STYLE_ADAPTERS[resolved]
    if resolved == "Realistic":
        text += " " + CAPTURE_ADAPTERS.get(capture, CAPTURE_ADAPTERS["Auto"])
    return ("VISUAL STYLE — " + resolved + "\n" + text
            + " Use this style unless the user's text explicitly asks for a different one. The style decides the medium "
              "and rendering; the target model decides how the prompt is written and the Director what it emphasizes.")
