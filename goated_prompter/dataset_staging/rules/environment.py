"""Feature and landmark visibility without assuming a primary subject."""

from . import Rule
from .visibility import required_readability


def environment_visibility(context):
    return required_readability(context, "environment feature")


ENVIRONMENT_RULES = (Rule("environment_visibility", environment_visibility),)
