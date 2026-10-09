"""Reference image roles, mappable attributes, sources and slots."""

REFERENCE_ROLE_NAMES = ("Auto", "Subject", "Scene", "Style", "Pose", "Composition", "Lighting")
REFERENCE_ATTRIBUTES = (
    ("subject", "Subject"),
    ("face", "Face / Identity"),
    ("outfit", "Outfit"),
    ("pose", "Pose"),
    ("composition", "Composition"),
    ("camera", "Camera"),
    ("scene", "Scene / Environment"),
    ("lighting", "Lighting"),
    ("colors", "Colors"),
    ("mood", "Mood / Style"),
    ("materials", "Materials"),
)
REFERENCE_SOURCE_NAMES = ("Auto", "Image 1", "Image 2", "Blend", "Off", "Image 3", "Image 4")
REFERENCE_IMAGE_SLOTS = (
    ("image", "Image 1"), ("image_2", "Image 2"),
    ("image_3", "Image 3"), ("image_4", "Image 4"),
)
REFERENCE_SOURCES = ("Off", "Image 1", "Image 2", "Image 3", "Image 4", "Blend")
