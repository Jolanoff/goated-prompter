"""Visual style choices shared by Builder and Dataset."""

STYLE_NAMES = ("Auto", "Anime", "Realistic", "Illustration", "3D render", "Product", "Painting")
# How a Realistic image was captured; only Realistic offers it. Auto lets the scene choose.
CAPTURE_NAMES = ("Auto", "Pro camera", "Phone snapshot", "Analog film")
# Styles a target model cannot render: Anima draws anime and illustration only.
UNSUPPORTED_STYLES = {"Anima": ("Realistic",)}
# Internal: no Style section at all (a Dataset style trigger carries the style). Never offered in the UI.
OFF_STYLE = "Off"
# A Mode whose task is a medium: with Style on Auto the Style follows it, so the medium is still set in one place.
MODE_STYLES = {"Photography": "Realistic", "Product": "Product"}
