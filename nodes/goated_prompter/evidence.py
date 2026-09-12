"""Structured per-image evidence extraction, caching, and deterministic scene resolution."""

import base64
from collections import OrderedDict
from dataclasses import dataclass
import hashlib
import json
import re
from threading import RLock

from .image_utils import EncodedImage
from .reference_map import REFERENCE_ATTRIBUTES, REFERENCE_IMAGE_SLOTS


EVIDENCE_SCHEMA_VERSION = "1"
EVIDENCE_SCHEMA_KEYS = tuple(key for key, _label in REFERENCE_ATTRIBUTES)

EVIDENCE_ANALYSIS_SYSTEM_PROMPT = """You are a visual evidence extractor. Analyze exactly one reference image independently.

Return one valid JSON object and nothing else. Use exactly these keys:
subject, face, outfit, pose, composition, camera, scene, lighting, colors, mood, materials

Each value must be a concise description of directly observable evidence for that attribute. Do not write a generation prompt. Do not infer hidden facts, identity history, brands, unreadable text, or uncertain small details. Use an empty string when an attribute is not clearly observable. Keep attributes separate: clothing belongs only in outfit; environment belongs only in scene; palette belongs only in colors."""


def evidence_analysis_user_message(source_label):
    return (
        f"Extract structured observable evidence from {source_label}. "
        "This is an independent analysis pass; no other reference image is available or relevant."
    )


def image_fingerprint(image):
    if not isinstance(image, EncodedImage):
        raise TypeError("Evidence analysis requires an EncodedImage.")
    try:
        payload = base64.b64decode(image.data, validate=False)
    except (ValueError, TypeError):
        payload = str(image.data).encode("utf-8", errors="replace")
    return hashlib.sha256(payload).hexdigest()


def evidence_cache_key(image, analysis_model):
    return image_fingerprint(image), str(analysis_model or "unknown"), EVIDENCE_SCHEMA_VERSION


def _clean_value(value):
    if value is None:
        return ""
    if isinstance(value, list):
        value = "; ".join(str(item) for item in value if item is not None)
    elif isinstance(value, dict):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return re.sub(r"\s+", " ", str(value)).strip()


def _normalized_key(value):
    compact = re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())
    aliases = {
        re.sub(r"[^a-z0-9]+", "", key.casefold()): key
        for key, _label in REFERENCE_ATTRIBUTES
    }
    aliases.update({
        re.sub(r"[^a-z0-9]+", "", label.casefold()): key
        for key, label in REFERENCE_ATTRIBUTES
    })
    aliases.update({"identity": "face", "environment": "scene", "style": "mood"})
    return aliases.get(compact)


@dataclass(frozen=True)
class ImageEvidence:
    fingerprint: str
    attributes: tuple

    def value_for(self, attribute):
        return next(value for key, value in self.attributes if key == attribute)

    def diagnostic_text(self):
        labels = dict(REFERENCE_ATTRIBUTES)
        return "\n".join(f"{labels[key]}: {value or '[not clearly observable]'}" for key, value in self.attributes)


def parse_image_evidence(text, fingerprint):
    value = str(text or "").strip()
    start = value.find("{")
    end = value.rfind("}")
    if start < 0 or end < start:
        raise ValueError("Image evidence analysis did not return a JSON object.")
    try:
        payload = json.loads(value[start:end + 1])
    except json.JSONDecodeError as exc:
        raise ValueError(f"Image evidence analysis returned invalid JSON: {exc.msg}.") from exc
    if not isinstance(payload, dict):
        raise ValueError("Image evidence analysis JSON must be an object.")

    normalized = {}
    for raw_key, raw_value in payload.items():
        key = _normalized_key(raw_key)
        if key and key not in normalized:
            normalized[key] = _clean_value(raw_value)
    attributes = tuple((key, normalized.get(key, "")) for key in EVIDENCE_SCHEMA_KEYS)
    if not any(value for _key, value in attributes):
        raise ValueError("Image evidence analysis returned no observable attributes.")
    return ImageEvidence(fingerprint=fingerprint, attributes=attributes)


class EvidenceCache:
    """Small process-local LRU cache; entries are immutable structured evidence."""

    def __init__(self, max_entries=64):
        self.max_entries = max(1, int(max_entries))
        self._entries = OrderedDict()
        self._lock = RLock()

    def get(self, key):
        with self._lock:
            evidence = self._entries.get(key)
            if evidence is not None:
                self._entries.move_to_end(key)
            return evidence

    def put(self, key, evidence):
        with self._lock:
            self._entries[key] = evidence
            self._entries.move_to_end(key)
            while len(self._entries) > self.max_entries:
                self._entries.popitem(last=False)

    def clear(self):
        with self._lock:
            self._entries.clear()


_EVIDENCE_CACHE = EvidenceCache()


def get_cached_evidence(key):
    return _EVIDENCE_CACHE.get(key)


def cache_evidence(key, evidence):
    _EVIDENCE_CACHE.put(key, evidence)


def clear_evidence_cache():
    _EVIDENCE_CACHE.clear()


@dataclass(frozen=True)
class ResolvedSceneAttribute:
    key: str
    label: str
    source: str
    evidence: str
    preserve: bool


@dataclass(frozen=True)
class ResolvedScene:
    attributes: tuple
    reference_map: object

    def value_for(self, attribute):
        return next(item.evidence for item in self.attributes if item.key == attribute)

    def source_for(self, attribute):
        return next(item.source for item in self.attributes if item.key == attribute)

    def diagnostic_text(self):
        return "\n".join(
            f"{item.label} <- {item.source}: {item.evidence}"
            for item in self.attributes
        )

    def compiler_input(self, target_model):
        lines = [
            "RESOLVED SCENE EVIDENCE",
            "This object was assembled deterministically in Python. Use only the selected evidence in each field; do not recover, substitute, or infer evidence from another reference.",
        ]
        for item in self.attributes:
            marker = " [PRESERVE]" if item.preserve else ""
            lines.append(f"{item.label} <- {item.source}{marker}:\n{item.evidence}")
        preserved = [f"{item.label} from {item.source}" for item in self.attributes if item.preserve]
        lines.append("PRESERVE:\n- " + "\n- ".join(preserved) if preserved else "PRESERVE:\nNone")
        lines.append(f"TARGET:\n{target_model}")
        lines.append(
            "COMPILER CONTRACT:\nConvert this resolved scene into one fluent target-specific prompt. "
            "Do not change attribute ownership and do not introduce conflicting evidence from an unselected image."
        )
        if self.reference_map.linked_references:
            lines.append(self.reference_map.to_instructions())
        return "\n\n".join(lines)


def build_resolved_scene(resolved_reference_map, image_1_evidence=None, image_2_evidence=None, user_prompt="", *, evidence_by_source=None):
    # Positional inputs remain supported for existing two-image callers.
    sources = evidence_by_source if evidence_by_source is not None else {
        "Image 1": image_1_evidence, "Image 2": image_2_evidence,
    }
    image_labels = {label for _field, label in REFERENCE_IMAGE_SLOTS}
    attributes = []
    for resolved in resolved_reference_map.attributes:
        if resolved.source in image_labels:
            if sources.get(resolved.source) is None:
                raise ValueError(f"Resolved {resolved.label} requires {resolved.source} evidence.")
            evidence = sources[resolved.source].value_for(resolved.key)
        elif resolved.source == "Blend":
            labels = resolved_reference_map.source_labels
            if len(labels) < 2 or any(sources.get(label) is None for label in labels):
                raise ValueError(f"Resolved {resolved.label} Blend requires evidence for all present images (at least two).")
            evidence = (
                "Deterministic attribute-scoped blend: "
                + "; ".join(f"{label} evidence: {sources[label].value_for(resolved.key) or 'not clearly observable'}" for label in labels)
                + f". Combine only compatible {resolved.label.lower()} characteristics."
            )
        elif resolved.source == "Off":
            evidence = "No reference evidence or preservation lock. Follow user direction freely for this attribute."
        else:
            evidence = f"User-requested transformation for {resolved.label}: {str(user_prompt or '').strip()}"
        if not evidence:
            evidence = "Not clearly observable in the assigned source; do not invent details."
        attributes.append(ResolvedSceneAttribute(
            key=resolved.key,
            label=resolved.label,
            source=resolved.source,
            evidence=evidence,
            preserve=resolved.preserve,
        ))
    return ResolvedScene(tuple(attributes), resolved_reference_map)
