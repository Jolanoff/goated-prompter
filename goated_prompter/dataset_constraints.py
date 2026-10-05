"""Small syntax compiler and separate exclusion/content checks; no domain tables.

This does not pretend to understand arbitrary English. Unsupported clauses stay
visible as unresolved rules; callers must not silently discard them.
"""

import json
from .planning.rule_compiler import compile_rules as compile_constraints
from .planning.constraint_validation import constraint_issues, positive_descriptions


CONSTRAINT_CONTRACT = """COMPILED CONSISTENCY / VARIATION RULES
Required facts stay fixed. Forbidden facts are internal restrictions: omit them
silently, never verbalize their absence or copy this data into positive prose.
Variation allowed is permission, not a requirement to change every property.
Unresolved rules need conservative interpretation; never invent missing facts.
Do not copy procedural required wording into descriptions: render known visible
attributes, not claims that a hairstyle is consistent or an eye color is the same.
When a fixed property has no supplied concrete value, leave it undescribed rather
than invent different values for different scenes. Never treat an unspecified
fixed value as permission for variation. Preserve any supplied concrete value.
Do not append sentences declaring excluded things absent or a surface clear of
them. Describe the actual intended surface, clothing or setting instead.
Literal requested in-image text remains literal text, not an exclusion command."""


def constraint_sections(text):
    compiled = compile_constraints(text)
    return "\n".join(label + "\n" + json.dumps(compiled[key], ensure_ascii=False)
                     for key, label in (("required", "REQUIRED FACTS"), ("forbidden", "FORBIDDEN FACTS"),
                                        ("variable", "VARIATION ALLOWED"), ("protected_literal", "PROTECTED LITERAL TEXT"),
                                        ("soft_preferences", "SOFT PREFERENCES"), ("unresolved", "UNRESOLVED RULES")))
