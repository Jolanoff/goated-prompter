"""Shared syntax-only rule compilation, with unsupported clauses retained."""

import re

QUOTED = re.compile(r'"(?:\\.|[^"\\])*"|(?<!\w)\'(?:\\.|[^\'\\\n])+\'(?!\w)|“[^”]*”|‘[^’]*’')


def compile_rules(text, *, source="constraints"):
    result = {key: [] for key in ("required", "forbidden", "variable", "protected_literal", "soft_preferences", "unresolved", "provenance")}
    literals = {}
    def mask(match):
        key = f"LITERAL{len(literals)}TOKEN"
        literals[key] = match[0]
        result["protected_literal"].append(match[0] if match[0].startswith("<d>") else match[0][1:-1])
        return key
    masked = re.sub(r"<d>.*?</d>", mask, str(text or ""), flags=re.S)
    masked = QUOTED.sub(mask, masked).replace("’", "'")
    clauses = re.split(r"(?<!\d)\.(?!\d)|[;\n]+|,\s*|\s+but\s+|\s+and\s+(?=(?:no|without|keep|same|do not|don't|avoid)\b)", masked, flags=re.I)
    for clause in clauses:
        clause = re.sub(r"^(?:but|and)\s+", "", clause.strip(), flags=re.I)
        if not clause:
            continue
        negative = re.fullmatch(r"(?:no|without|avoid|exclude|(?:do not|don't|never)\s+(?:use|wear|include|add|show|render))\s+(.+)", clause, re.I)
        variable = re.fullmatch(r"(.+?)\s+(?:may|can|could)\s+(?:vary|change|differ)", clause, re.I)
        variable_prefix = re.fullmatch(r"(?:vary|allow variation (?:in|of))\s+(.+)", clause, re.I)
        # Nominal exclusions only: a title/name/sign or predicate may describe
        # visible content, rather than instruct its removal. Preserve ambiguity.
        ambiguous_negative = negative and bool(re.search(
            r"\b(?:sign|slogan|title|named|called|if|when|because|is|are|was|were|has|have|should|must)\b", clause, re.I))
        ambiguous_negative = ambiguous_negative or negative and bool(re.match(r"(?i:no|without)\s+[A-Z]\w+", clause))
        ambiguous_negative = ambiguous_negative or negative and bool(re.search(r"\bnot\b", negative[1], re.I))
        preference = re.fullmatch(r"(?:prefer|ideally)\s+(.+)", clause, re.I)
        if re.search(r"\b(?:unless|except|only if)\b", clause, re.I) or ambiguous_negative:
            facts, category = [clause], "unresolved"
        elif preference:
            facts, category = [preference[1]], "soft_preferences"
        elif negative and not any(key in clause for key in literals):
            facts = re.split(r"\s+(?:or|and)\s+", negative[1], flags=re.I)
            category = "forbidden"
        elif variable or variable_prefix:
            facts = [(variable or variable_prefix)[1]]
            category = "variable"
        elif re.search(r"\b(?:no|not|don't|without|unless|except|avoid|never)\b", clause, re.I):
            facts, category = [clause], "unresolved"
        else:
            facts, category = [clause], "required"
        for fact in facts:
            source_text = clause
            for key, literal in literals.items():
                fact = fact.replace(key, literal)
                source_text = source_text.replace(key, literal)
            fact = re.sub(r"^(?:a|an|the|any)\s+", "", fact.strip(), flags=re.I) if category == "forbidden" else fact.strip()
            if fact and fact not in result[category]:
                result[category].append(fact)
                result["provenance"].append({"value": fact, "kind": category,
                    "source": source, "source_text": source_text,
                    "confidence": "low" if category == "unresolved" else "high"})
    for key, literal in literals.items():
        result["provenance"].append({"value": literal if literal.startswith("<d>") else literal[1:-1], "kind": "protected_literal",
                                   "source": source, "source_text": literal, "confidence": "high"})
    return result
