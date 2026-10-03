"""Product presentation/readability, not body/head/hand rules."""

from . import Rule
from .visibility import required_readability


def product_visibility(context):
    return required_readability(context, "product")


PRODUCT_RULES = (Rule("product_visibility", product_visibility),)
