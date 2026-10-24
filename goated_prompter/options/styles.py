"""Visual style choices shared by Builder and Dataset."""

# Style families; a family may offer sub-styles, chosen as one value "Family / Sub-style". Realistic has none: its
# capture is its sub-choice.
STYLE_FAMILIES = ("Auto", "Anime", "Realistic", "Cinematic", "Semi-realistic", "Illustration", "Concept art", "Comic",
                  "Manga", "Pixel art", "Sketch", "3D render", "Product", "Painting")
SUB_STYLES = {
    "Anime": ("Modern TV anime", "90s cel anime", "Anime film", "Watercolor anime", "Chibi"),
    "Cinematic": ("Blockbuster", "Indie drama", "Neo-noir", "Vintage film"),
    "Semi-realistic": ("Painterly", "Game splash art", "Soft fantasy"),
    "Illustration": ("Children's book", "Flat vector", "Ink and wash", "Fashion illustration", "Retro poster"),
    "Concept art": ("Environment", "Character", "Keyframe"),
    "Comic": ("Superhero", "Noir", "Ligne claire", "Webtoon"),
    "Manga": ("Shonen", "Shojo", "Seinen"),
    "Pixel art": ("8-bit", "16-bit", "Isometric"),
    "Sketch": ("Pencil", "Charcoal", "Ink pen"),
    "3D render": ("Stylized cartoon", "Realistic CGI", "Low poly", "Clay"),
    "Product": ("Studio white", "Lifestyle", "Dark and moody"),
    "Painting": ("Oil", "Watercolor", "Gouache", "Impressionist", "Ink wash"),
}
SUB_STYLE_SEPARATOR = " / "
STYLE_NAMES = STYLE_FAMILIES + tuple(f"{family}{SUB_STYLE_SEPARATOR}{sub}" for family in STYLE_FAMILIES
                                     for sub in SUB_STYLES.get(family, ()))
# How a Realistic image was captured; only Realistic offers it. Auto lets the scene choose.
CAPTURE_NAMES = ("Auto", "Pro camera", "Phone snapshot", "Analog film", "Instant film", "Disposable camera", "Black-and-white film", "Medium format", "Studio portrait",
                 "Fashion editorial", "Documentary", "Street photography", "Flash snapshot", "Mirror selfie",
                 "Webcam", "Security camera", "Action camera", "Drone")
# Choices that make an image without colour: style families (with every sub-style) and captures.
NO_COLOR_STYLES = ("Manga", "Sketch")
NO_COLOR_CAPTURES = ("Black-and-white film",)
# Styles a target model cannot render: Anima draws anime and illustration only, never a photograph.
UNSUPPORTED_STYLES = {"Anima": ("Realistic", "Cinematic")}
# Internal: no Style section at all (a Dataset style trigger carries the style). Never offered in the UI.
OFF_STYLE = "Off"
# A Mode whose task is a medium: with Style on Auto the Style follows it, so the medium is still set in one place.
MODE_STYLES = {"Photography": "Realistic", "Product": "Product"}


def style_family(name):
    """The family of a style value ("Anime" for "Anime / Chibi"); anything else comes back unchanged."""
    return name.split(SUB_STYLE_SEPARATOR, 1)[0] if isinstance(name, str) else name


def without_color(style, capture="Auto"):
    """Whether this style and capture make an image without colour."""
    return style_family(style) in NO_COLOR_STYLES or capture in NO_COLOR_CAPTURES
