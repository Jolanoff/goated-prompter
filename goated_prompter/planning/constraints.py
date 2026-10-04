"""Safely compile standalone request rules without interpreting every 'no'."""

from dataclasses import dataclass, replace
import json
import re

from .rule_compiler import compile_rules as compile_constraints


@dataclass(frozen=True)
class CompiledRequest:
    original: str
    positive_request: str
    required: tuple = ()
    forbidden: tuple = ()
    variable: tuple = ()
    protected_literals: tuple = ()
    workflow_rules: str = None

    def workflow_data(self):
        return {key: list(getattr(self, key)) for key in ("required", "forbidden", "variable", "protected_literals")}

    def writer_request(self, *, include_constraints=True):
        text = self.positive_request
        if not (self.forbidden or self.variable):
            return text
        text = text or "Apply the requested constraints to the preserved reference scene."
        if not include_constraints:
            return text
        return text + "\n\nCOMPILED USER REQUIREMENTS (internal, not image text)\n" + json.dumps(self.workflow_data(), ensure_ascii=False)


def compile_request(text, *, has_context=False):
    # Match only rule clauses delimited outside opaque literals and dialogue tags.
    literals = []
    def mask(match):
        literals.append(match[0])
        return f"PROTECTEDLITERAL{len(literals) - 1}TOKEN"
    masked = re.sub(r'<d>.*?</d>|"[^"\n]*"|“[^”\n]*”|(?<!\w)\'[^\'\n]*\'(?!\w)', mask, text, flags=re.S)
    parts = re.split(r"((?<!\d)\.(?!\d)|[;,\n]+|\s+but\s+)", masked, flags=re.I)
    accepted, positive, retained = [], [], []
    for index in range(0, len(parts), 2):
        clause = parts[index]
        value = clause.strip()
        if not value:
            continue
        parsed = compile_constraints(value)
        title = bool(re.match(r"(?i:no|without)\s+[A-Z]\w+", value))
        # Compile nominal exclusion clauses only. Mixed positive/negative clauses,
        # predicates, names and exclusions that describe a sign/concept stay raw.
        ambiguous = bool(re.search(r"['’]|\b(?:sign|slogan|title|named|called|if|when|because|is|are|was|were|has|have|should|must)\b|\band\s+\w+ing\b", value, re.I))
        if parsed["forbidden"] and index + 2 < len(parts) and parts[index + 1].startswith(","):
            following = parts[index + 2].strip()
            next_rule = compile_constraints(following)
            # A comma can continue the scope of 'do not use A, B or C'. Unless
            # the next clause is clearly independent, do not remove its prefix.
            independent = bool(next_rule["forbidden"] or next_rule["variable"] or
                               re.match(r"(?:a|an|the)\s+", following, re.I))
            ambiguous |= bool(following and not independent)
        safe = (not title and not ambiguous and "PROTECTEDLITERAL" not in value
                and not parsed["unresolved"] and not parsed["required"])
        if safe and (parsed["forbidden"] or parsed["variable"]):
            accepted.append(parsed)
        else:
            positive.append(clause)
            retained.append(clause + (parts[index + 1] if index + 1 < len(parts) else ""))
    # An exclusion can itself be the subject ('no smoking sign'). Without another
    # positive clause or existing evidence, retain the original request verbatim.
    if not accepted or not positive and not has_context:
        return CompiledRequest(text, text, protected_literals=tuple(literals))
    def restore(value):
        for index, literal in enumerate(literals):
            value = value.replace(f"PROTECTEDLITERAL{index}TOKEN", literal)
        return value
    positive_request = restore(re.sub(r"(?:[;,\s]+|\s+but\s*)+$", "", "".join(retained), flags=re.I).strip())
    required = []
    for clause in positive:
        match = re.search(r"\bwith\s+(.+)$", clause, re.I)
        if match and "PROTECTEDLITERAL" not in match[1]:
            required.append(match[1].strip())
    return CompiledRequest(text, positive_request, tuple(required),
        tuple(dict.fromkeys(fact for rules in accepted for fact in rules["forbidden"])),
        tuple(dict.fromkeys(fact for rules in accepted for fact in rules["variable"])), tuple(literals))


def compile_prompt_request(request, *, has_context=False):
    compiled = compile_request(request.idea, has_context=has_context)
    rules = compile_request(request.custom_instructions, has_context=has_context or bool(request.idea.strip()))
    merged = {key: tuple(dict.fromkeys((*getattr(compiled, key), *getattr(rules, key))))
              for key in ("required", "forbidden", "variable", "protected_literals")}
    return replace(compiled, **merged, workflow_rules=rules.positive_request)


COMPILED_CONTRACT = """Compiled required facts remain fixed; forbidden facts are internal
restrictions. Apply them silently by omission, never write no X, without X or
X-free into positive descriptions. Variation is permission, not a requirement.
Forbidden facts are NOT a request to describe absence or declare compliance.
Never turn internal exclusion data into a descriptive trait. Protected requested
text/dialogue stays exact. Unsupported rules remain part of
the authoritative user request, not discarded. Do not copy internal data labels."""
