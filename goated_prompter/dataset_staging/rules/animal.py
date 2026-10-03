"""Animal staging uses common presentation rules, never human anatomy."""

from . import Rule
from .visibility import required_readability


def animal_visibility(context):
    return required_readability(context, "animal")


ANIMAL_RULES = (Rule("animal_visibility", animal_visibility),)
