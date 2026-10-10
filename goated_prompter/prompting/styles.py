"""Visual style text for the selected Style option."""

from ..options.targets import canonical_target

STYLE_ADAPTERS = {
    "Anime": "Anime / manga art: clean line art, cel or soft shading, anime character proportions and expressive faces, "
             "a vivid designed palette. Do not use photographic camera, lens, skin-pore or film-grain language.",
    "Realistic": "Photorealistic photograph of a real moment: say how it was captured and name the light source and "
                 "its direction. Describe people, fabric and surfaces as a camera records them, with the small "
                 "imperfections that belong to this scene rather than a stock list. Prefer candid moments in lived-in "
                 "places over posed perfection, and avoid praise words such as stunning or flawless. Keep every word "
                 "photographic.",
    "Illustration": "Stylized 2D illustration: deliberate linework or shapes, a designed color palette and "
                    "non-photographic rendering suited to the subject.",
    "3D render": "3D rendered image: modeled forms, physically based materials, render-style lighting and a clean "
                 "computer-graphics finish.",
    "Product": "Commercial product photography: the product is the hero, with accurate shape, materials and finish, "
               "a clean studio or styled set and controlled lighting with defined reflections.",
    "Painting": "Painting: visible brushwork, painterly color mixing and the texture of a traditional medium "
                "(oil, watercolor or gouache, whichever fits the idea).",
}


def resolve_style(style, target=None):
    """Return the effective style name. Auto lets the request decide, except Anima is anime-native."""
    if style in STYLE_ADAPTERS:
        return style
    return "Anime" if canonical_target(target) == "Anima" else "Auto"


def style_section(style, target=None):
    """Return the prompt section for the effective style, or an empty string for Auto."""
    resolved = resolve_style(style, target)
    if resolved == "Auto":
        return ""
    return ("VISUAL STYLE — " + resolved + "\n" + STYLE_ADAPTERS[resolved]
            + " Use this style unless the user's text explicitly asks for a different one.")
