"""Deterministic, target-independent reference attribute resolution."""

from dataclasses import dataclass
import re

from .prompt_catalog import (
    REFERENCE_ATTRIBUTES,
    REFERENCE_IMAGE_SLOTS,
    REFERENCE_MANUAL_CONSTRAINTS as _MANUAL_CONSTRAINTS,
    REFERENCE_SOURCE_NAMES,
)


def reference_images(value):
    """Return present images in stable slot order, without renumbering sparse slots."""
    return {label: getattr(value, field, None) for field, label in REFERENCE_IMAGE_SLOTS
            if getattr(value, field, None) is not None}


REFERENCE_MAP_FIELDS = tuple(f"reference_{key}_source" for key, _label in REFERENCE_ATTRIBUTES)

_ATTRIBUTE_LABELS = dict(REFERENCE_ATTRIBUTES)
_PRESERVE_ATTRIBUTES = {
    # Outfit is intentionally independent: preserving a subject must not pull
    # clothing back from the subject source when Outfit has its own assignment.
    "subject": ("subject", "face"),
    "composition": ("composition",),
    "camera": ("camera",),
    "materials": ("materials",),
    "lighting": ("lighting",),
    "colors": ("colors",),
}
_LEGACY_ROLE_ATTRIBUTES = {
    "Subject": ("subject", "face", "outfit", "pose"),
    "Scene": ("scene", "composition", "camera"),
    "Style": ("mood", "colors", "materials"),
    "Pose": ("pose",),
    "Composition": ("composition", "camera"),
    "Lighting": ("lighting", "colors", "mood"),
}
_SECONDARY_AUTO_ATTRIBUTES = {"lighting", "colors", "mood"}
_PRIMARY_DIRECTORS = {"Reverse Engineer", "Surgical Edit"}

_EXPLICIT_PATTERNS = {
    "subject": (
        r"\b(?:add|remove|replace|swap|change)\b.{0,48}\b(?:subject|person|character|woman|man|girl|boy|animal|object)\b",
        r"\b(?:turn|make)\b.{0,32}\b(?:her|him|them|subject|person|character)\b",
    ),
    "face": (
        r"\b(?:change|replace|swap|alter|use)\b.{0,40}\b(?:face|identity|likeness|facial features|hair)\b",
        r"\bface\s+(?:from|of)\s+(?:image|reference)\b",
    ),
    "outfit": (
        r"\b(?:change|replace|swap|dress|redress|use)\b.{0,48}\b(?:outfit|clothes|clothing|wardrobe|dress|shirt|jacket|coat|uniform)\b",
        r"\b(?:wearing|wears|dressed in)\b",
    ),
    "pose": (
        r"\b(?:change|replace|match|use|adopt)\b.{0,40}\b(?:pose|posture|gesture|action|stance)\b",
        r"\b(?:make|have)\b.{0,28}\b(?:sit|stand|walk|run|kneel|turn|look|reach|hold)\b",
    ),
    "composition": (
        r"\b(?:change|replace|match|use|reframe|crop)\b.{0,44}\b(?:composition|framing|crop|layout|placement)\b",
        r"\b(?:center|reposition|reframe|recrop)\b",
    ),
    "camera": (
        r"\b(?:change|replace|match|use|switch)\b.{0,44}\b(?:camera|angle|viewpoint|perspective|lens|shot)\b",
        r"\b(?:low-angle|high-angle|close-up|wide shot|overhead view|eye-level)\b",
    ),
    "scene": (
        r"\b(?:change|replace|swap|remove)\b.{0,52}\b(?:scene|environment|background|location|room|setting)\b",
        r"\b(?:put|place|move|set)\b.{0,60}\b(?:in|into|at|on)\s+(?!(?:this|that)\b)",
    ),
    "lighting": (
        r"\b(?:change|replace|match|use|transfer|make)\b.{0,44}\b(?:light|lighting|illumination|shadows|exposure)\b",
        r"\b(?:relight|backlight|front-light)\b",
    ),
    "colors": (
        r"\b(?:change|replace|match|use|transfer|make)\b.{0,44}\b(?:color|colour|palette|hue|grading|tones?)\b",
        r"\b(?:recolor|colourize|colorize)\b",
    ),
    "mood": (
        r"\b(?:change|replace|match|use|transfer|make)\b.{0,44}\b(?:mood|style|aesthetic|atmosphere|look)\b",
        r"\b(?:cinematic|editorial|dreamy|moody|playful|ominous)\b",
    ),
    "materials": (
        r"\b(?:change|replace|match|use|transfer|make)\b.{0,44}\b(?:material|fabric|wood|metal|stone|glass|texture|finish|surface)\b",
        r"\b(?:retexture|resurface)\b",
    ),
}


def normalize_reference_source(value):
    compact = re.sub(r"[^a-z0-9]+", "", str(value or "Auto").casefold())
    aliases = {
        "auto": "Auto",
        "1": "Image 1",
        "image1": "Image 1",
        "reference1": "Image 1",
        "2": "Image 2",
        "image2": "Image 2",
        "reference2": "Image 2",
        "blend": "Blend",
        "both": "Blend",
        "off": "Off",
        "3": "Image 3",
        "image3": "Image 3",
        "reference3": "Image 3",
        "4": "Image 4",
        "image4": "Image 4",
        "reference4": "Image 4",
    }
    return aliases.get(compact, "Auto")


def _diagnostic_source(source):
    return {
        "Auto": "auto",
        "Image 1": "image_1",
        "Image 2": "image_2",
        "Image 3": "image_3",
        "Image 4": "image_4",
        "Off": "off",
        "Blend": "blend",
        "User Prompt": "user_prompt",
    }.get(source, str(source or "unknown"))


def _log_section(title, lines):
    print(title, flush=True)
    for line in lines:
        print(line, flush=True)


def reference_map_from_mapping(values):
    values = values if isinstance(values, dict) else {}
    return {
        key: normalize_reference_source(values.get(f"reference_{key}_source"))
        for key, _label in REFERENCE_ATTRIBUTES
    }


def _explicit_user_attributes(text):
    value = str(text or "").casefold()
    return {
        attribute
        for attribute, patterns in _EXPLICIT_PATTERNS.items()
        if any(re.search(pattern, value) for pattern in patterns)
    }


def _legacy_assignments(image_1_role, image_2_role, has_image_1, has_image_2):
    assignments = {}
    for role, source, available in (
        (str(image_1_role or "Auto"), "Image 1", has_image_1),
        (str(image_2_role or "Auto"), "Image 2", has_image_2),
    ):
        if not available:
            continue
        for attribute in _LEGACY_ROLE_ATTRIBUTES.get(role, ()):
            assignments.setdefault(attribute, source)
    return assignments


def _preserved_attributes(request):
    preserved = set()
    for field, attributes in _PRESERVE_ATTRIBUTES.items():
        if bool(getattr(request, f"preserve_{field}", False)):
            preserved.update(attributes)
    return preserved


def _validate_manual_source(attribute, source, source_labels):
    label = _ATTRIBUTE_LABELS[attribute]
    if source.startswith("Image ") and source not in source_labels:
        raise ValueError(f"Reference Map assigns {label} to {source}, but {source} is not connected.")
    if source == "Blend" and len(source_labels) < 2:
        raise ValueError(f"Reference Map assigns {label} to Blend, but at least two connected images are required.")


@dataclass(frozen=True)
class ResolvedReferenceAttribute:
    key: str
    label: str
    source: str
    preserve: bool
    reason: str


@dataclass(frozen=True)
class ResolvedReferenceMap:
    attributes: tuple
    source_labels: tuple = ("Image 1", "Image 2")
    linked_references: bool = False

    def source_for(self, attribute):
        return next(item.source for item in self.attributes if item.key == attribute)

    def reason_for(self, attribute):
        return next(item.reason for item in self.attributes if item.key == attribute)

    def hard_manual_constraints(self):
        constraints = []
        for item in self.attributes:
            if item.reason != "manual Reference Map assignment":
                continue
            if item.source == "Off":
                constraints.append(f"{item.label} is Off: use no reference evidence; the user may freely direct this attribute.")
                continue
            if item.source == "Blend":
                constraints.append(
                    f"Blend {item.label.lower()} evidence from {' and '.join(self.source_labels)} only for this attribute; "
                    "do not blend unrelated attributes."
                )
                continue
            other = ", ".join(source for source in self.source_labels if source != item.source) or "any other source"
            constraints.append(_MANUAL_CONSTRAINTS[item.key].format(source=item.source, other=other))
        return tuple(constraints)

    def director_constraints(self):
        lines = []
        for source in (*self.source_labels, "Blend", "Off", "User Prompt"):
            controlled = [item.label for item in self.attributes if item.source == source]
            if controlled:
                lines.append(f"{source} controls: " + ", ".join(controlled))
        hard = self.hard_manual_constraints()
        if hard:
            lines.append("Hard manual constraints:")
            lines.extend(f"- {constraint}" for constraint in hard)
        return "\n".join(lines)

    def to_instructions(self):
        if self.linked_references:
            return "\n".join([
                "LINKED REFERENCE SOURCE MAP",
                "Each row independently controls both source and strict preservation. Do not reassign any source.",
                *[f"{item.label}: {item.source}; preserve={item.preserve}." for item in self.attributes],
                *self.hard_manual_constraints(),
                "Source selections are strict locks, even when the user's text requests a contradictory transformation. "
                "Resolve that conflict by retaining the locked evidence, not replacing it. "
                "Words such as cinematic or wearing do not override a lock. "
                "Off means no reference evidence and no preservation constraint for that row; follow user direction freely. "
                "Subject does not lock face, outfit, or any other row. "
                "Blend includes all present sources: " + ", ".join(self.source_labels) + ". "
                "Combine only compatible evidence for the selected attribute; omit uncertain details rather than inventing them.",
            ])
        lines = [
            "REFERENCE SOURCE MAP",
            "This attribute map was resolved before generation. Do not reinterpret it, assign a different source, or let target-model optimization change it.",
        ]
        for source in (*self.source_labels, "Blend", "Off", "User Prompt"):
            controlled = [item.label for item in self.attributes if item.source == source]
            if controlled:
                lines.append(f"{source} controls:\n- " + "\n- ".join(controlled))

        preserved = [f"{item.label} from {item.source}" for item in self.attributes if item.preserve]
        if preserved:
            lines.append(
                "PRESERVE LOCKS\n- " + "\n- ".join(preserved)
                + "\nKeep each locked attribute faithful to its resolved source except for the exact transformation explicitly requested by the user."
            )

        manual_constraints = self.hard_manual_constraints()
        if manual_constraints:
            lines.append(
                "HARD MANUAL SOURCE CONSTRAINTS\n- " + "\n- ".join(manual_constraints)
                + "\nThese are hard constraints. They override Auto resolution, primary-image bias, and Director preset defaults."
            )

        lines.append(
            "REFERENCE CONFLICT RULES\n"
            "- The explicit current transformation is authoritative only for the attributes it changes.\n"
            "- Manual Reference Map assignments are already resolved here and override automatic source selection.\n"
            "- When references conflict, use the assigned source for that attribute and do not borrow the conflicting version from another image.\n"
            "- Blend is intentional: combine compatible evidence from all present images only for that named attribute; do not blend unrelated attributes or whole scenes.\n"
            "- Attributes assigned to User Prompt follow the requested transformation while unrelated reference-controlled attributes remain unchanged.\n"
            "- Do not invent readable text, brand names, labels, book titles, logos, or uncertain small details. Generalize or omit uncertain evidence instead of hallucinating."
        )
        return "\n\n".join(lines)


def resolve_reference_map(request, director_name=None):
    source_labels = tuple(reference_images(request))
    linked = getattr(request, "linked_references", False)
    has_image_1 = request.image is not None
    has_image_2 = request.image_2 is not None
    manual = {
        key: normalize_reference_source(source)
        for key, source in (request.reference_map or {}).items()
        if key in _ATTRIBUTE_LABELS
    }
    manual = {key: manual.get(key, "Auto") for key, _label in REFERENCE_ATTRIBUTES}
    if linked:
        manual = {key: "Off" if source == "Auto" else source for key, source in manual.items()}
    if source_labels:
        _log_section(
            "[Goated Prompter Reference Map INPUT]",
            [f"{label} = {_diagnostic_source(manual[key])}" for key, label in REFERENCE_ATTRIBUTES],
        )
    for attribute, source in manual.items():
        if source != "Auto":
            _validate_manual_source(attribute, source, source_labels)

    explicit = _explicit_user_attributes(request.idea)
    legacy = _legacy_assignments(request.image_1_role, request.image_2_role, has_image_1, has_image_2)
    preserved = _preserved_attributes(request)
    primary = next(iter(source_labels), "User Prompt")

    resolved = []
    for attribute, label in REFERENCE_ATTRIBUTES:
        if linked:
            source, reason = manual[attribute], "manual Reference Map assignment"
        elif attribute in explicit:
            source, reason = "User Prompt", "explicit user transformation"
        elif manual[attribute] != "Auto":
            source, reason = manual[attribute], "manual Reference Map assignment"
        elif attribute in legacy:
            source, reason = legacy[attribute], "legacy Image Role shortcut"
        elif attribute in preserved:
            source, reason = primary, "Preserve lock on primary reference"
        elif not source_labels:
            source, reason = "User Prompt", "text-only request"
        elif has_image_1 and has_image_2 and director_name not in _PRIMARY_DIRECTORS and attribute in _SECONDARY_AUTO_ATTRIBUTES:
            source, reason = "Image 2", "automatic secondary-reference treatment source"
        else:
            source, reason = primary, "automatic primary-reference source"
        resolved.append(ResolvedReferenceAttribute(
            key=attribute,
            label=label,
            source=source,
            preserve=(source != "Off" if linked else attribute in preserved and source != "Off"),
            reason=reason,
        ))
    result = ResolvedReferenceMap(tuple(resolved), source_labels, linked)
    if source_labels:
        _log_section(
            "[Goated Prompter Reference Map RESOLVED]",
            [
                f"{item.label} = {_diagnostic_source(item.source)} "
                f"(preserve={'on' if item.preserve else 'off'}; {item.reason})"
                for item in result.attributes
            ],
        )
    return result
