"""Visual style text for the selected Style option.

Three layers write a prompt and none overrides another: the target model owns how the prompt is written (format,
syntax, order, length), the Style owns the medium and rendering (and, for Realistic, how the image was captured), and
the Director owns what is emphasized inside them.
"""

from ..options.styles import MODE_STYLES, OFF_STYLE, STYLE_NAMES, SUB_STYLE_SEPARATOR, UNSUPPORTED_STYLES, style_family
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
                 "hair, fabric that creases and pulls under tension, wear on surfaces. Anything that does not exist today "
                 "(futuristic, science-fiction or fantasy machines, clothing, creatures or places) is a real built "
                 "object photographed on location: name its materials, construction and wear, and how its own lights "
                 "actually light the people and surfaces around it, never a digital effect or a glow without a source. "
                 "No praise or quality words; every word stays photographic.",
    "Illustration": "Stylized 2D illustration: deliberate linework or shapes, a designed color palette and "
                    "non-photographic rendering suited to the subject.",
    "3D render": "3D rendered image: modeled forms, physically based materials, render-style lighting and a clean "
                 "computer-graphics finish.",
    "Product": "Commercial product photography: crisp, controlled rendering of materials with defined reflections "
               "and highlights and a polished advertising finish.",
    "Painting": "Painting: visible brushwork, painterly color mixing and the texture of a traditional medium "
                "(oil, watercolor or gouache, whichever fits the idea).",
    "Cinematic": "Cinematic film still: a real photograph taken on a film set, every person, prop and place a physical "
                 "thing in front of the camera. Motivated lighting with a clear key, fill and practical sources in the "
                 "scene, a deliberate color grade, the depth of field of a cinema lens and a composition that frames "
                 "the moment. Anything that does not exist today is a built prop or set photographed for real, never "
                 "a digital effect.",
    "Semi-realistic": "Semi-realistic digital painting: real anatomy, light and materials rendered with a painter's "
                      "simplification, slightly idealized faces and proportions, smooth painterly skin and soft "
                      "edges; between an illustration and a photograph, never a photograph.",
    "Concept art": "Concept art: a painted design image that explains the subject, its shapes, materials and scale, "
                   "with confident brushwork, value structure that reads at a glance and a limited palette.",
    "Comic": "Western comic art: bold inked outlines with varied line weight, flat or cel color, strong blacks for "
             "shadow and dynamic, readable poses.",
    "Manga": "Manga: black-and-white ink linework, screentone shading, expressive faces and speed or impact lines "
             "where the action needs them; no color.",
    "Pixel art": "Pixel art: a low-resolution image built from visible square pixels, a small fixed palette, hard "
                 "pixel edges and no blur or smooth gradients.",
    "Sketch": "Pencil sketch: graphite lines on paper, construction lines and hatching for shadow, unfinished edges "
              "and no color.",
}

# What a sub-style adds to its family's text (options/styles.py SUB_STYLES).
SUB_STYLE_ADAPTERS = {
    "Anime": {
        "Modern TV anime": "Current TV anime look: clean digital line art, crisp cel shading with soft gradient highlights and bright, saturated color.",
        "90s cel anime": "1990s cel anime look: hand-painted cels, slightly grainy flat color, thicker uneven line art, muted palette and painted backgrounds.",
        "Anime film": "Feature-film anime look: richly painted backgrounds, detailed lighting and atmosphere, careful character acting and lush color.",
        "Watercolor anime": "Anime figures with watercolor rendering: soft bleeding edges, paper texture, light washes of color and delicate line art.",
        "Chibi": "Chibi proportions: oversized heads about a third of the body, small rounded bodies, simplified features and playful expressions.",
    },
    "Cinematic": {
        "Blockbuster": "Big-budget look: bold teal and orange grade, dramatic backlight and rim light, wide lens and epic scale.",
        "Indie drama": "Independent drama look: natural available light, muted grade, intimate handheld framing and quiet, honest moments.",
        "Neo-noir": "Neo-noir look: hard low-key light, deep shadows, saturated neon or sodium practicals, rain or haze and tense framing.",
        "Vintage film": "Look of a film from decades ago: softer contrast, warm faded color, gentle grain and the costume and set design of its era.",
    },
    "Semi-realistic": {
        "Painterly": "Visible brush strokes over realistic forms, color laid in confident patches, edges lost and found.",
        "Game splash art": "Game splash-art finish: dynamic heroic posing, polished rendering, dramatic rim light and a vivid, high-contrast palette.",
        "Soft fantasy": "Soft fantasy rendering: dreamy diffused light, pastel and jewel tones, delicate glow and gentle, idealized features.",
    },
    "Illustration": {
        "Children's book": "Children's book illustration: friendly rounded shapes, warm gentle palette, textured paper and clear, simple storytelling.",
        "Flat vector": "Flat vector illustration: clean geometric shapes, solid color fills, no texture and a limited modern palette.",
        "Ink and wash": "Ink and wash: expressive pen lines with loose watercolor washes laid over them.",
        "Fashion illustration": "Fashion illustration: elongated elegant figures, quick confident marker and ink strokes, garments in focus, minimal background.",
        "Retro poster": "Mid-century poster illustration: bold simplified shapes, limited flat palette, printed grain and strong graphic composition.",
    },
    "Concept art": {
        "Environment": "Environment concept: the place is the subject, with clear scale, depth, atmosphere and a readable path through the image.",
        "Character": "Character concept: the figure's design reads clearly from silhouette to costume and props, with a simple supporting background.",
        "Keyframe": "Keyframe concept: one dramatic story moment with staged lighting, strong composition and clear action.",
    },
    "Comic": {
        "Superhero": "Superhero comic look: muscular dynamic anatomy, foreshortened action poses, saturated primaries and heavy inks.",
        "Noir": "Noir comic look: stark black and white with heavy spot blacks, hard shadows and minimal accent color.",
        "Ligne claire": "Ligne claire: uniform clean outlines, flat unshaded color and detailed, orderly backgrounds.",
        "Webtoon": "Webtoon look: clean digital line art, soft cel shading, bright screen-friendly color and a vertical-scroll feel.",
    },
    "Manga": {
        "Shonen": "Shonen manga look: energetic action, bold speed lines, sharp angular features and high-impact panels.",
        "Shojo": "Shojo manga look: delicate fine lines, large expressive eyes, flowers and sparkles in the screentone and soft emotion.",
        "Seinen": "Seinen manga look: detailed realistic linework, dense hatching, mature restrained expressions and gritty backgrounds.",
    },
    "Pixel art": {
        "8-bit": "8-bit look: very low resolution, a palette of a few colors and blocky simple sprites.",
        "16-bit": "16-bit look: moderate resolution, a richer palette, dithering and detailed sprites and tiles.",
        "Isometric": "Isometric pixel art: a fixed isometric angle, clean pixel edges and blocky three-quarter forms.",
    },
    "Sketch": {
        "Pencil": "Graphite pencil: fine controlled lines, soft tonal shading and smudged blends.",
        "Charcoal": "Charcoal: bold dark strokes, rich blacks, smudged soft tones and visible paper grain.",
        "Ink pen": "Ink pen: crisp black lines with cross-hatching for shadow and no gray tones.",
    },
    "3D render": {
        "Stylized cartoon": "Stylized cartoon 3D: exaggerated rounded proportions, smooth materials, soft bounce light and a bright palette.",
        "Realistic CGI": "Realistic CGI: physically accurate materials, subsurface skin, ray-traced light and detailed surfaces.",
        "Low poly": "Low poly 3D: visible flat-shaded facets, simple geometry and a clean limited palette.",
        "Clay": "Clay or stop-motion look: soft handmade clay forms, fingerprints and tool marks, slightly imperfect shapes and miniature-set lighting.",
    },
    "Product": {
        "Studio white": "Seamless white studio background, soft even light and a clean shadow under the product.",
        "Lifestyle": "The product in use in a real, lived-in setting with natural light and people or hands around it.",
        "Dark and moody": "Dark background, sculpted low-key light, strong highlights tracing the product's edges.",
    },
    "Painting": {
        "Oil": "Oil paint: rich saturated color, thick impasto in the lights and smooth blending in the shadows.",
        "Watercolor": "Watercolor: transparent washes, soft bleeding edges, white paper showing through and granulating pigment.",
        "Gouache": "Gouache: opaque matte color, flat even areas and crisp edges.",
        "Impressionist": "Impressionist painting: broken visible brush strokes, vibrating color and light captured over detail.",
        "Ink wash": "Ink wash painting: black ink in graded washes, expressive brush strokes and generous empty space.",
    },
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
    "Instant film": "Capture: an instant film print. Soft focus, low contrast, shifted and slightly washed-out colors, "
                    "a fixed wide lens, often a direct flash, and the square print look; never a clean digital look.",
    "Disposable camera": "Capture: a cheap disposable film camera. Harsh on-camera flash with hard falloff into dark "
                         "backgrounds, fixed focus, visible grain, slightly soft corners and casual, imperfect framing.",
    "Black-and-white film": "Capture: black-and-white film. No color; tones from deep blacks to bright whites, visible "
                            "grain and contrast shaped by the light, the lens character of a film camera.",
    "Medium format": "Capture: a medium format camera. Very fine detail, smooth tonal gradation, a shallow depth of field "
                     "with gentle focus falloff and a calm, deliberate composition.",
    "Studio portrait": "Capture: a studio portrait. A dedicated camera with a portrait lens, controlled studio light "
                       "(key, fill and rim from named directions), a plain or seamless backdrop and precise focus on the eyes.",
    "Fashion editorial": "Capture: a fashion editorial shoot. A dedicated camera, styled posing, strong deliberate light "
                         "(hard sun, strobe or ring light), a bold location or set and a polished magazine finish.",
    "Documentary": "Capture: documentary photojournalism. A dedicated camera with a moderate wide lens, available light "
                   "only, an unposed moment caught as it happens and honest, unretouched detail.",
    "Street photography": "Capture: street photography. A small camera with a wide prime lens at eye level, available "
                          "light, a candid moment in a public place and passersby or traffic around the subject.",
    "Flash snapshot": "Capture: a direct on-camera flash at night or indoors. Bright frontal flash on the subject, hard "
                      "shadows just behind, a dark falloff in the background and a candid party-photo feel.",
    "Mirror selfie": "Capture: a mirror selfie. The person holds a phone that is visible in the mirror, the reflection "
                     "shows them and the room behind, phone wide-angle perspective and the light of the room.",
    "Webcam": "Capture: a laptop or desk webcam. Fixed low-resolution wide view from slightly below or at eye level, soft "
              "detail, compression noise and the room's own mixed light, often a screen glow on the face.",
    "Security camera": "Capture: a security camera. A high corner angle looking down, wide distorted lens, low "
                       "resolution, flat light or night infrared in grayscale, and a timestamp overlay.",
    "Action camera": "Capture: a small action camera. An ultra-wide fisheye perspective with curved edges, deep focus, "
                     "close to the subject and mounted or handheld in motion.",
    "Drone": "Capture: an aerial drone camera. A high overhead or angled view from tens of meters up, the subject small "
             "in a wide view of the place around it, crisp and evenly exposed.",
}


def resolve_style(style, target=None, mode=None):
    """Return the effective style name. Auto lets the request decide, except that a Mode whose task is a medium
    (MODE_STYLES) sets it and Anima is anime-native; a style the target cannot render (Realistic on Anima) falls back
    the same way."""
    target = canonical_target(target)
    if style == OFF_STYLE:
        return OFF_STYLE  # something else carries the style; not even Anima's default applies
    known = lambda name: name in STYLE_NAMES and name != "Auto"
    if not known(style):
        style = MODE_STYLES.get(mode, style)
    if known(style) and style_family(style) not in UNSUPPORTED_STYLES.get(target, ()):
        return style
    return "Anime" if target == "Anima" else "Auto"


def style_section(style, target=None, capture="Auto", mode=None):
    """Return the prompt section for the effective style, or an empty string for Auto."""
    resolved = resolve_style(style, target, mode)
    if resolved in ("Auto", OFF_STYLE):
        return ""
    family, _, sub = resolved.partition(SUB_STYLE_SEPARATOR)
    text = STYLE_ADAPTERS[family] + (" " + SUB_STYLE_ADAPTERS[family][sub] if sub else "")
    if resolved == "Realistic":
        text += " " + CAPTURE_ADAPTERS.get(capture, CAPTURE_ADAPTERS["Auto"])
    return ("VISUAL STYLE — " + resolved + "\n" + text
            + " Use this style unless the user's text explicitly asks for a different one. The style decides the medium "
              "and rendering; the target model decides how the prompt is written and the Director what it emphasizes.")
