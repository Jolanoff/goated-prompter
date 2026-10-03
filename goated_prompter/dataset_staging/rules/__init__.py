"""Rule protocol and explicit registry. Rules have no dependency on Dataset quality."""

import re
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class GeometryIssue:
    code: str
    fields: tuple[str, ...]
    severity: str
    message: str
    repair: str


@dataclass(frozen=True)
class GeometryContext:
    row: dict
    geometry: dict
    dataset_type: str | None
    rule_groups: tuple[str, ...]

    @property
    def scene(self):
        return self.row.get("scene", "").casefold().replace("–", "-").replace("—", "-")

    @property
    def reflected(self):
        return bool(re.search(r"\b(?:mirror|reflection|reflected)\b", self.scene))

    @property
    def multiple_views(self):
        return bool(re.search(r"\b(?:collage|inset|split.screen)\b", self.scene))

    @property
    def action(self):
        return (self.row.get("idea", "") + " " + self.geometry.get("action_focus", "")).casefold()

    @property
    def focus(self):
        return " ".join(self.geometry.get("visibility_focus", [])).casefold()

    def asserted(self, pattern):
        if self.reflected or self.multiple_views:
            return False
        return any(not re.search(r"\b(?:no|not|never|without|avoid)\b[^,.;:]*$",
                                 self.scene[max(0, match.start() - 40):match.start()])
                   for match in re.finditer(pattern, self.scene))


@dataclass(frozen=True)
class Rule:
    name: str
    check: Callable[[GeometryContext], list[GeometryIssue]]
    guidance: str = ""


def issue(code, fields, message, *, repair=None, severity="error"):
    return GeometryIssue(code, tuple(fields), severity, message, repair or message)


# Imports are intentionally after the protocol definitions to avoid engine/rule
# cycles. All selection happens in this registry and StagingProfile.rule_groups.
from .camera import CAMERA_RULES
from .orientation import SUBJECT_ORIENTATION_RULES
from .framing import COMMON_FRAMING_RULES
from .visibility import VISIBILITY_RULES
from .prose import PROSE_RULES
from .character import CHARACTER_RULES
from .multiple_characters import MULTI_CHARACTER_RULES
from .animal import ANIMAL_RULES
from .product import PRODUCT_RULES
from .environment import ENVIRONMENT_RULES
from .brand_text import BRAND_TEXT_RULES

COMMON_RULES = (*CAMERA_RULES, *SUBJECT_ORIENTATION_RULES, *COMMON_FRAMING_RULES, *VISIBILITY_RULES, *PROSE_RULES)
RULE_GROUPS = {
    "character": CHARACTER_RULES, "multiple_characters": MULTI_CHARACTER_RULES,
    "animal": ANIMAL_RULES, "product": PRODUCT_RULES,
    "environment": ENVIRONMENT_RULES, "brand_text": BRAND_TEXT_RULES,
}


def rules_for(groups):
    return tuple(rule for group in groups for rule in RULE_GROUPS[group])
