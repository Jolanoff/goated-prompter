"""Detect tag-list loops without merging separate character blocks."""

from collections import Counter
import re


MIN_LOOP_TAGS = 12
MIN_TAG_REPETITIONS = 3
MAX_ANIMA_TAGS = 100
_QUOTED = re.compile(r'"(?:[^"\\]|\\.)*"|“[^”]*”')
_TAG = re.compile(r"\(?([a-z0-9][a-z0-9_ /+-]{0,79})(?::\d+(?:\.\d+)?)?\)?", re.I)
_LABEL = re.compile(r"^[^,():;\n]{1,100}:\s*")


def anima_tags(text, *, tag_only=False):
    """Read the leading inventory; a blank line explicitly starts scene prose."""
    value = str(text or "")
    sections = [value] if tag_only else re.split(r"\r?\n[ \t]*\r?\n", value, maxsplit=1)
    explicit_boundary = len(sections) == 2
    tags = []
    for field in re.split(r"[,;\r\n]", sections[0]):
        field = field.strip()
        if not field:
            continue
        if not _TAG.fullmatch(field):
            field = _LABEL.sub("", field)
        candidate = re.sub(r":\d+(?:\.\d+)?(?=\)?$)", "", field)
        if not field:
            continue
        if not re.fullmatch(r"[\w ()\\/+'-]+", candidate):
            break
        # Legacy inline prose uses sentence case. New writer output separates
        # tags and prose explicitly; supplied inventories are counted literally.
        if not tag_only and not explicit_boundary and re.match(r"[A-Z]", candidate) and "(" not in candidate:
            break
        tags.append(field)
    return tags


def anima_tag_count(text, *, tag_only=False):
    return len(anima_tags(text, tag_only=tag_only))


def repeated_tag(text, protected_terms=()):
    """Return a looping tag in one block, excluding literals and protected anchors."""
    value = str(text or "")
    value = _QUOTED.sub(lambda match: " " * len(match.group()), value)
    for term in sorted((term for term in protected_terms if term), key=len, reverse=True):
        value = value.replace(term, "\0")
    # Comma continuation lines belong together; named or blank-separated blocks do not.
    value = re.sub(r",[ \t]*\r?\n(?![ \t]*(?:\r?\n|[^,():\r\n]{1,100}:))[ \t]*", ", ", value)
    value = re.sub(r";[ \t]*(?=[^,():;\n]{1,100}:)", "\n", value)
    for line in value.splitlines():
        blocks = [[]]
        for field in line.split(","):
            field = field.strip()
            label = _LABEL.match(field) if not _TAG.fullmatch(field) else None
            if label:
                blocks.append([])
                field = field[label.end():]
            match = _TAG.fullmatch(field)
            if match and len(match[1].split()) <= 4:
                blocks[-1].append(re.sub(r"[ _]+", "_", match[1].strip().casefold()))
        for tags in blocks:
            if len(tags) >= MIN_LOOP_TAGS:
                for tag, count in Counter(tags).most_common():
                    if count >= MIN_TAG_REPETITIONS:
                        return tag
    return None


_PLURAL_COUNT = re.compile(r"\(?(?:([2-9]|\d{2,})\+?(?:boys|girls|others)|multiple (?:boys|girls|others))(?::\d+(?:\.\d+)?)?\)?", re.I)
_SINGLE_COUNT = re.compile(r"\(?1(?:boy|girl|other)(?::\d+(?:\.\d+)?)?\)?", re.I)
_SOLO_FIELD = r"\(?solo(?::\d+(?:\.\d+)?)?\)?"


def remove_contradictory_solo(text):
    """Drop the solo tag when the count tags describe several characters.

    Danbooru-style solo means exactly one character, so it cannot coexist with
    3boys, multiple girls or two or more single-character count tags. Only the
    leading tag inventory is edited; scene prose and solo focus are kept.
    """
    value = str(text or "")
    tags = [tag.strip() for tag in anima_tags(value)]
    singles = sum(bool(_SINGLE_COUNT.fullmatch(tag)) for tag in tags)
    if not any(re.fullmatch(_SOLO_FIELD, tag, re.I) for tag in tags):
        return value
    if not (singles >= 2 or any(_PLURAL_COUNT.fullmatch(tag) for tag in tags)):
        return value
    head, separator, rest = (re.split(r"(\r?\n[ \t]*\r?\n)", value, maxsplit=1) + ["", ""])[:3]
    head = re.sub(r",[ \t]*" + _SOLO_FIELD + r"[ \t]*(?=,|\r?\n|$)", "", head, flags=re.I | re.M)
    head = re.sub(r"^[ \t]*" + _SOLO_FIELD + r"[ \t]*,[ \t]*", "", head, flags=re.I | re.M)
    return head + separator + rest


def anima_tag_key(tag):
    """Compare tags ignoring case, spacing, underscores, escapes and weights."""
    value = re.sub(r":\d+(?:\.\d+)?\)?$", "", tag.strip()).replace("\\", "")
    if value.startswith("(") and not value.endswith(")"):
        value = value[1:]
    return re.sub(r"[\s_]+", "", value.casefold())


def drop_supplied_tags(text, supplied):
    """Remove tags already present in the app-inserted inventory from generated scene tags.

    Only a leading tag block separated from the prose by a blank line is edited;
    returns None when the output has no such block so callers keep their checks.
    """
    parts = re.split(r"(\r?\n[ \t]*\r?\n)", str(text or ""), maxsplit=1)
    if len(parts) != 3:
        return None
    head, separator, rest = parts
    keys = {anima_tag_key(tag) for tag in anima_tags(supplied, tag_only=True)}
    kept = [field.strip() for field in re.split(r"[,;\r\n]", head) if field.strip() and anima_tag_key(field) not in keys]
    return ", ".join(kept) + separator + rest
