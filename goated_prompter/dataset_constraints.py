"""Small syntax compiler and separate exclusion/content checks; no domain tables.

This does not pretend to understand arbitrary English. Unsupported clauses stay
visible as unresolved rules; callers must not silently discard them.
"""

import json
import re


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


def compile_constraints(text):
    result = {key: [] for key in ("required", "forbidden", "variable", "unresolved")}
    # Quoted content is opaque: 'a sign reads NO HAT' is not a wardrobe rule.
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


def constraint_sections(text):
    compiled = compile_constraints(text)
    return "\n".join(label + "\n" + json.dumps(compiled[key], ensure_ascii=False)
                     for key, label in (("required", "REQUIRED FACTS"), ("forbidden", "FORBIDDEN FACTS"),
                                        ("variable", "VARIATION ALLOWED"), ("unresolved", "UNRESOLVED RULES")))


def positive_descriptions(prompt, target):
    if target != "Ideogram4":
        return [prompt]
    value = json.loads(prompt)
    return [value["high_level_description"], value["compositional_deconstruction"]["background"],
            *[text for text in value["style_description"].values() if isinstance(text, str)],
            *[element["desc"] for element in value["compositional_deconstruction"]["elements"]]]


def constraint_issues(text, compiled, protected_terms=()):
    """A: forbidden positive content. B: verbalized exclusion. Kept distinct.

    Match only supplied noun/state wording, not every possible 'no X'. Mere
    ambiguous mentions are warnings; explicit object assertions can be repaired.
    """
    from .dataset_visible_content import _QUOTED
    for term in protected_terms:
        if term:
            text = text.replace(term, "[protected anchor]")
    # Mask only explicitly rendered literals, not arbitrary quoted assertions.
    def literal(match):
        before = text[max(0, match.start() - 80):match.start()]
        return "[literal]" if re.search(r"\b(?:reads?|says?|text|lettering|printed|written|inscription)\b[^.;]*$", before, re.I) else match.group()
    text = _QUOTED.sub(literal, text)
    issues = []
    for fact in compiled["forbidden"]:
        words = re.findall(r"\w+(?:[-']\w+)*", fact)
        if len(words) > 1 and words[0].casefold() == "visible":
            words = words[1:]  # Image content is visible; this qualifier is scope.
        if not words:
            continue
        # Scene/setting suffixes describe scope, not an object to look for.
        if len(words) > 1 and words[-1].casefold() in {"scene", "scenes", "setting", "settings"}:
            words = words[:-1]
        last = words[-1]
        variants = re.escape(last)
        if len(last) > 2:
            variants += "|" + re.escape(last[:-1] if last.endswith("s") and not last.endswith("ss") else last + "s")
        # Keep compound facts contiguous: arbitrary gaps per word can backtrack
        # explosively on repeated clauses and turn ambiguous mentions into errors.
        # Unknown paraphrases/inserted qualifiers remain Deep Review's job.
        pattern = r"\b" + r"\s+".join(map(re.escape, words[:-1]))
        if len(words) > 1:
            pattern += r"\s+"
        pattern += "(?:" + variants + r")\b"
        for match in re.finditer(pattern, text, re.I):
            before = re.split(r"[.;,!?\n]", text[:match.start()])[-1]
            after = re.split(r"[.;,!?\n]", text[match.end():], maxsplit=1)[0]
            excluded = re.search(r"\b(?:no|without|avoid|(?:clear|free)\s+of|(?:do not|don't|never|not)\s+(?:wear\w*|us\w*|show\w*|includ\w*))\b[^.;,!?]*$", before, re.I)
            excluded = excluded or re.match(r"\s+(?:(?:is|are|was|were)\s+)?(?:absent|excluded|omitted|not\s+(?:visible|present|shown|included))\b", after, re.I)
            if excluded:
                code, severity = "constraint_negative_leakage", "error"
            else:
                assertion = re.search(r"\b(?:wear\w*|hold\w*|carrying|carries|contains?|featuring|with|a|an|the)\b[^.;,!?]*$", before, re.I)
                code, severity = "forbidden_content", "error" if assertion else "warning"
            issue = {"code": code, "severity": severity,
                     "message": ("A forbidden fact was stated in positive content: " if code == "forbidden_content" else
                                 "An exclusion was verbalized in positive content: ") + fact + ". Apply compiled restrictions silently."}
            if issue not in issues:
                issues.append(issue)
    return issues
