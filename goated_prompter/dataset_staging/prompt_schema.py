"""Planner vocabulary generated from the same registry/profile as validation."""

from .profiles import get_profile
from .schema import GEOMETRY_FIELDS
from .rules import COMMON_RULES, rules_for


def geometry_prompt_schema(dataset_type, *, optional_values_in_context=False):
    profile = get_profile(dataset_type)
    lines = [f"STAGING SCHEMA — {dataset_type}",
             "Required fields: " + (", ".join(sorted(profile.required)) or "none; use only applicable staging"),
             "Recommended fields (optional): " + (", ".join(sorted(profile.recommended)) or "none"),
             "Allowed fields only; omission of optional helper metadata is not a contradiction:"]
    for name, spec in GEOMETRY_FIELDS.items():
        if name not in profile.allowed:
            continue
        values = profile.values_for(name)
        kind = ("enum; allowed values in optional_geometry_values" if optional_values_in_context and values is not None and name not in profile.required else
                ", ".join(sorted(values)) if values is not None else
                f"integer >= {spec.minimum}" if spec.count else
                f"array of up to {spec.max_items} short strings" if spec.text_array else
                f"free text, at most {spec.max_length} characters")
        lines.append(f"{name}: {kind}. {spec.description}")
    lines.append("Scene prose remains authoritative for individual/unusual staging. Do not invent facts to fill optional fields.")
    lines.extend(rule.guidance for rule in (*COMMON_RULES, *rules_for(profile.rule_groups)) if rule.guidance)
    return "\n".join(lines)


def geometry_enum_values(dataset_type):
    profile = get_profile(dataset_type)
    return {name: sorted(profile.values_for(name)) for name, spec in GEOMETRY_FIELDS.items()
            if name in profile.allowed and spec.values is not None}
