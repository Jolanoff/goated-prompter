"""Shared positive-content validation; exclusion leakage and actual violations differ."""

import re
import json
from .rule_compiler import QUOTED


def positive_descriptions(prompt, target):
    if target != "Ideogram4":
        return [prompt]
    value = json.loads(prompt)
    return [value["high_level_description"], value["compositional_deconstruction"]["background"],
            *[text for text in value["style_description"].values() if isinstance(text, str)],
            *[element["desc"] for element in value["compositional_deconstruction"]["elements"]]]


def constraint_issues(text, compiled, protected_terms=()):
    for term in protected_terms:
        if term:
            text = text.replace(term, "[protected anchor]")
    text = re.sub(r"<d>.*?</d>", "[protected dialogue]", text, flags=re.S)
    def literal(match):
        before = text[max(0, match.start() - 80):match.start()]
        return "[literal]" if re.search(r"\b(?:reads?|says?|text|lettering|printed|written|inscription|named|called|title)\b[^.;]*$", before, re.I) else match.group()
    text = QUOTED.sub(literal, text)
    issues = []
    for fact in compiled.get("forbidden", ()):
        words = re.findall(r"\w+(?:[-']\w+)*", fact)
        if len(words) > 1 and words[0].casefold() == "visible":
            words = words[1:]
        if not words:
            continue
        if len(words) > 1 and words[-1].casefold() in {"scene", "scenes", "setting", "settings"}:
            words = words[:-1]
        last = words[-1]
        variants = re.escape(last)
        if len(last) > 2:
            variants += "|" + re.escape(last[:-1] if last.endswith("s") and not last.endswith("ss") else last + "s")
        pattern = r"\b" + r"\s+".join(map(re.escape, words[:-1]))
        if len(words) > 1:
            pattern += r"\s+"
        pattern += "(?:" + variants + r")\b"
        for match in re.finditer(pattern, text, re.I):
            before = re.split(r"[.;,!?\n]", text[:match.start()])[-1]
            after = re.split(r"[.;,!?\n]", text[match.end():], maxsplit=1)[0]
            excluded = re.search(r"\b(?:no|without|avoid|(?:clear|free)\s+of|(?:do not|don't|never|not)\s+(?:wear\w*|us\w*|show\w*|includ\w*))\b[^.;,!?]*$", before, re.I)
            excluded = excluded or re.match(r"\s+(?:(?:is|are|was|were)\s+)?(?:absent|excluded|omitted|not\s+(?:visible|present|shown|included))\b", after, re.I)
            excluded = excluded or re.match(r"[- ]free\b", text[match.end():], re.I)
            excluded = excluded or re.search(r"\b(?:absence|lack)\s+of\s+(?:any\s+|visible\s+)?$", before, re.I)
            if excluded:
                code, severity = "constraint_negative_leakage", "error"
            else:
                assertion = re.search(r"\b(?:wear\w*|hold\w*|carrying|carries|contains?|featuring|with|a|an|the)\b[^.;,!?]*$", before, re.I)
                compound = re.match(r"-\w", text[match.end():])
                code, severity = "forbidden_content", "error" if assertion and not compound else "warning"
            issue = {"code": code, "severity": severity,
                     "message": ("A forbidden fact was stated in positive content: " if code == "forbidden_content" else
                                 "An exclusion was verbalized in positive content: ") + fact + ". Apply compiled restrictions silently."}
            if issue not in issues:
                issues.append(issue)
    return issues


def output_constraint_issues(prompt, target, compiled):
    descriptions = positive_descriptions(prompt, target)
    if target == "MiniMax H3":
        match = re.search(r"(?ms)^integrated_multimodal_description:\s*(.*?)(?=^[a-z_]+:|\Z)", prompt)
        descriptions = [match[1]] if match else descriptions
    return [issue for text in descriptions for issue in constraint_issues(text, compiled)]
