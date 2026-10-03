"""Visual readability only. Exact lettering/brand protection stays in workflows."""

from . import Rule
from .visibility import required_readability


def brand_text_visibility(context):
    return required_readability(context, "logo/text element")


BRAND_TEXT_RULES = (Rule("brand_text_visibility", brand_text_visibility),)
