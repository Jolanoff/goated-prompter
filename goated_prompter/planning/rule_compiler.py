"""Shared syntax-only rule compilation, with unsupported clauses retained."""

import re


def compile_rules(text):
    result = {key: [] for key in ("required", "forbidden", "variable", "unresolved")}
    pieces = re.split(r"(\"[^\"]*\"|(?<!\w)'[^'\n]*'(?!\w)|“[^”]*”)", str(text or ""))
    literals = {}
    for index in range(1, len(pieces), 2):
        key = f"LITERAL{index}TOKEN"
        literals[key] = pieces[index]
        pieces[index] = key
    masked = "".join(pieces).replace("’", "'")
    clauses = re.split(r"(?<!\d)\.(?!\d)|[;\n]+|,\s*|\s+but\s+|\s+and\s+(?=(?:no|without|keep|same|do not|don't|avoid)\b)", masked, flags=re.I)
    for clause in clauses:
        clause = re.sub(r"^(?:but|and)\s+", "", clause.strip(), flags=re.I)
        if not clause:
            continue
        negative = re.fullmatch(r"(?:no|without|avoid|exclude|(?:do not|don't|never)\s+(?:use|wear|include|add|show|render))\s+(.+)", clause, re.I)
        variable = re.fullmatch(r"(.+?)\s+(?:may|can|could)\s+(?:vary|change|differ)", clause, re.I)
        variable_prefix = re.fullmatch(r"(?:vary|allow variation (?:in|of))\s+(.+)", clause, re.I)
        if re.search(r"\b(?:unless|except|only if)\b", clause, re.I):
            facts, category = [clause], "unresolved"
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
            for key, literal in literals.items():
                fact = fact.replace(key, literal)
            fact = re.sub(r"^(?:a|an|the|any)\s+", "", fact.strip(), flags=re.I) if category == "forbidden" else fact.strip()
            if fact and fact not in result[category]:
                result[category].append(fact)
    return result
