"""Understanding v10: the request as structured intent for review and optional vocabulary matching.

The Understanding model returns `intent` in the same call as the rest of the brief. It is an interpretation,
never an authority: the brief's summary, fixed, randomized, must and avoid stay what the scene writer uses, and
nothing here can change them. Code checks the structure (check), fills defaults and links subjects to the
expanded cast (normalize) and reports what looks doubtful (warnings) without rewriting it. A reviewer may
correct links and search terms or drop the model's own suggestions (reviewed); everything the request states
stays as it is, and a change to that goes through Revise, which analyzes the request again.

Normalized form (brief["intent"]):
  available   false when the model's intent cannot be safely retained: then elements, relations and
              unresolved are empty and warnings say why. The rest of the brief is unaffected.
  elements    [{id, kind, text, status, source, character, member, cast, of, by, to, input, terms}]
                kind      subject, action, pose, object, body_part, attribute, environment, aspect
                text      the user's words for it
                status    fixed (every image), randomized (a dimension that varies), optional (allowed),
                          excluded (ruled out)
                source    request (the request, rules or guided inputs say it) or suggested (a dimension to
                          vary that the user did not name; only with status randomized)
                character the character a subject stands for, as its cast label without a number ("man"
                          for "man 1" and "man 2"), or ""
                member    which one of identical people a subject is (2 = "man 2"), or 0 for the whole group
                          (or a character of one). Briefs stored before it existed have no member: 0.
                cast      the people that subject is ("man 2", or "man 1", "man 2" for the group), set by code
                of        the subject, object or body part an object, attribute or body part belongs to, or ""
                by, to    who does an action (or holds a pose) and to what: element ids
                input     the guided input (1-based) this element belongs to only, or 0 for every image
                terms     other words or broader concepts, only as evidence for later matching
  relations   [{id, a, rel, b, status}]: a link between two elements in the user's words ("behind")
  unresolved  the model's notes on what the request leaves unclear, never guessed
  truncated   the model reported more parts than fit
  warnings    code's notes for review (doubtful wording, a clash with avoid); recomputed after every edit

People: the brief's characters list is who appears; subject parts say which of them a part is about. A part
names one person (member) or a whole group of identical people. When the model gives one part per person of a
group without numbering them, code numbers them in order: identical people are interchangeable, so that only
names them. Fewer parts than people, unnumbered, cannot be told apart: that is reported, never guessed. A
character with no subject part gets one (from the characters list, which the request states), unless a subject
not tied to any character may already stand for them.

Wording checks compare word forms (general English plural and verb endings), never meanings, so they only warn,
and only where it matters: a part required in every image (or ruled out) that the request does not seem to say.
"""

from collections import Counter
import re

from ...vocabulary.semantic import NEGATIONS, STOPWORDS, split_negated, stem

KINDS = ("subject", "action", "pose", "object", "body_part", "attribute", "environment", "aspect")
STATUSES = ("fixed", "randomized", "optional", "excluded")
SOURCES = ("request", "suggested")
RELATION_STATUSES = ("fixed", "optional", "excluded")
MAX_ELEMENTS, MAX_RELATIONS, MAX_UNRESOLVED = 24, 12, 6
MAX_TERMS, MAX_REVIEW_TERMS = 3, 6
MAX_TEXT, MAX_TERM, MAX_NOTE, MAX_LINKS = 80, 40, 160, 8
REQUIRED = ("id", "kind", "text", "status", "source")
OPTIONAL = ("character", "member", "of", "by", "to", "input", "terms")
EMPTY = {"character": "", "member": 0, "of": "", "by": [], "to": [], "input": 0, "terms": []}   # a field that does not apply
STORED = (*REQUIRED, *OPTIONAL, "cast")
MAX_MEMBER = 20
FIELD_KINDS = {"character": ("subject",), "member": ("subject",), "of": ("object", "body_part", "attribute"),
               "by": ("action", "pose"), "to": ("action",)}
OWNERS = ("subject", "object", "body_part")       # valid ownership targets
NO_TARGET = ("attribute", "aspect")                # what an action cannot be done to
ID = re.compile(r"^[a-z][a-z0-9_]{0,15}$")
WORD = re.compile(r"[^\W_]+")
# English nouns whose plural is not formed with -s: a closed grammatical class, shared with the characters list
# (understanding._singular), so "2 men" and "man" are one word everywhere.
IRREGULAR_PLURALS = {"men": "man", "women": "woman", "people": "person", "children": "child", "feet": "foot",
                     "teeth": "tooth", "mice": "mouse", "geese": "goose"}
NUMBER_WORDS = frozenset("one two three four five six seven eight nine ten eleven twelve".split())
UNAVAILABLE_NOTE = "Optional details unavailable: "


def model_schema():
    """The JSON schema of the model's `intent` key."""
    text = {"type": "string", "maxLength": MAX_TEXT}
    ids = {"type": "array", "maxItems": MAX_LINKS, "items": {"type": "string", "maxLength": 16}}
    properties = {
        "id": {"type": "string", "maxLength": 16}, "kind": {"type": "string", "enum": list(KINDS)}, "text": text,
        "status": {"type": "string", "enum": list(STATUSES)}, "source": {"type": "string", "enum": list(SOURCES)},
        "character": {**text, "description": "Subject only: its characters label."},
        "member": {"type": "integer", "minimum": 1, "maximum": MAX_MEMBER,
                   "description": "Subject only: which identical person; omit for a group."},
        "of": {"type": "string", "maxLength": 16,
               "description": "Ownership of an object, body_part or attribute: id of its subject, object or body_part owner."},
        "by": {**ids, "description": "Action or pose only: subject ids of the participants. Never put by on an object."},
        "to": {**ids, "description": "Action only: target part ids, not attributes or aspects. Never put to on an object."},
        "input": {"type": "integer", "minimum": 1, "maximum": 20},
        "terms": {"type": "array", "maxItems": MAX_TERMS, "items": {"type": "string", "maxLength": MAX_TERM},
                  "description": "Reliable semantic alternatives, not echoes of text. Empty when none; never invent synonyms."}}
    variants = {}
    for kind in KINDS:
        fields = tuple(field for field, kinds in FIELD_KINDS.items() if kind in kinds)
        variants.setdefault(fields, []).append(kind)
    element = {"anyOf": [{"type": "object", "additionalProperties": False, "required": list(REQUIRED), "properties": {
        **{key: properties[key] for key in (*REQUIRED, "input", "terms", *fields)},
        "kind": {"type": "string", "enum": kinds}}} for fields, kinds in variants.items()]}
    relation = {"type": "object", "additionalProperties": False, "required": ["a", "rel", "b", "status"], "properties": {
        "a": {"type": "string", "maxLength": 16},
        "rel": {**text, "description": "Non-action link only, such as position or a stated tie. Do not repeat an action."},
        "b": {"type": "string", "maxLength": 16},
        "status": {"type": "string", "enum": list(RELATION_STATUSES)}}}
    return {"type": "object", "additionalProperties": False, "required": ["elements", "relations"], "properties": {
        "elements": {"type": "array", "maxItems": MAX_ELEMENTS, "items": element},
        "relations": {"type": "array", "maxItems": MAX_RELATIONS, "items": relation},
        "unresolved": {"type": "array", "maxItems": MAX_UNRESOLVED, "items": {"type": "string", "maxLength": MAX_NOTE}},
        "truncated": {"type": "boolean"}}}


# ---------------------------------------------------------------- the contract

def _label_key(label):
    return " ".join(WORD.findall(str(label).casefold()))


def _present(item):
    """An element without its empty optional fields (anything else is returned as it is, for check to report)."""
    if not isinstance(item, dict):
        return item
    return {key: field for key, field in item.items() if key not in EMPTY or field != EMPTY[key]}


def prepare(value):
    """Model-boundary empty values only. Keep every nonempty field and every unknown key for validation."""
    if not isinstance(value, dict) or not isinstance(value.get("elements"), list):
        return value
    return {**value, "elements": [
        {key: field for key, field in item.items() if not (key in EMPTY and (
            field is None or key in ("character", "of") and isinstance(field, str) and not field.strip()))}
        if isinstance(item, dict) else item for item in value["elements"]]}


def _ownership_cycles(known):
    cyclic = set()
    for ident in known:
        path, current = [], ident
        while isinstance(current, str) and current in known and current not in path:
            path.append(current)
            current = known[current].get("of")
        if isinstance(current, str) and current in path:
            cyclic.update(path[path.index(current):])
    return cyclic


def sanitize(value, characters, guided):
    """Keep the first interpretation; unavailable optional annotations never become guessed facts.

    Identity, scope and requested facts must already pass the existing contract. Links and hints are
    restored unchanged only when they pass that same contract; no second semantic validator or model call.
    """
    value = prepare(value)
    if not isinstance(value, dict) or not isinstance(value.get("elements"), list) or any(
            not isinstance(item, dict) for item in value["elements"]):
        return value, []
    notes = []
    originals = [item for item in value["elements"] if item.get("source") != "suggested"]
    for item in value["elements"]:
        if item.get("source") == "suggested" and item.get("status") != "randomized":
            notes.append(f'{UNAVAILABLE_NOTE}{item.get("id", "part")} was a suggestion, not a user requirement; omitted.')
    annotations = ("of", "by", "to", "terms")
    kept = {**value, "elements": [{key: field for key, field in item.items() if key not in annotations}
                                  for item in originals], "relations": []}
    if check(kept, characters, guided):
        return kept, notes  # an invalid identity, scope or fact cannot be made valid by guessing
    cyclic = _ownership_cycles({item["id"]: item for item in originals})
    for item, original in zip(kept["elements"], originals):
        for field in annotations:
            if field not in original:
                continue
            item[field] = original[field]
            problems = check(kept, characters, guided)
            if (field == "of" and item["id"] in cyclic) or problems:
                del item[field]
                notes.append(f'{UNAVAILABLE_NOTE}{item["id"]}.{field} could not be validated; no replacement inferred.')
    relations = value.get("relations")
    if not isinstance(relations, list) or len(relations) > MAX_RELATIONS:
        notes.append(f"{UNAVAILABLE_NOTE}relationships could not be validated.")
    else:
        for number, relation in enumerate(relations, 1):
            kept["relations"].append(relation)
            if check(kept, characters, guided):
                kept["relations"].pop()
                notes.append(f"{UNAVAILABLE_NOTE}relationship {number} could not be validated; no replacement inferred.")
    return kept, notes


def check(value, characters, guided, *, max_terms=MAX_TERMS):
    """Contract errors in the model's intent; [] when it is valid.

    characters: {label a subject may name: how many people it stands for} (the model's characters entries, or
    character_counts of a brief); guided: how many guided inputs there are."""
    if not isinstance(value, dict):
        return ["intent must be an object with elements and relations."]
    if not {"elements", "relations"} <= set(value) or set(value) - {"elements", "relations", "unresolved", "truncated"}:
        return ["intent needs elements and relations, and may add only unresolved and truncated."]
    errors = []
    elements, relations = value["elements"], value["relations"]
    if not isinstance(elements, list) or len(elements) > MAX_ELEMENTS:
        return [f"intent.elements must be a list of at most {MAX_ELEMENTS} parts (set truncated when more do not fit)."]
    if not isinstance(relations, list) or len(relations) > MAX_RELATIONS:
        return [f"intent.relations must be a list of at most {MAX_RELATIONS} links."]
    # Empty optional fields from older endpoints or the stored form mean the field does not apply.
    elements = [_present(item) for item in elements]
    known, labels = {}, {}
    for label, count in characters.items():
        labels[_label_key(label)] = labels.get(_label_key(label), 0) + count
    for number, item in enumerate(elements, 1):
        where = f"intent.elements[{number}]"
        if not isinstance(item, dict) or not set(REQUIRED) <= set(item) or set(item) - set(REQUIRED) - set(OPTIONAL):
            errors.append(f"{where} needs id, kind, text, status and source, and may add only {', '.join(OPTIONAL)}.")
            continue
        ident = item["id"]
        if not isinstance(ident, str) or not ID.match(ident) or ident in known:
            errors.append(f"{where}.id must be a short unique id like \"s1\".")
            continue
        known[ident] = item
        if item["kind"] not in KINDS:
            errors.append(f"{where}.kind must be one of {', '.join(KINDS)}.")
        if not isinstance(item["text"], str) or not item["text"].strip() or len(item["text"]) > MAX_TEXT:
            errors.append(f"{where}.text must be the user's words, at most {MAX_TEXT} characters.")
        if item["status"] not in STATUSES:
            errors.append(f"{where}.status must be one of {', '.join(STATUSES)}.")
        if item["source"] not in SOURCES:
            errors.append(f'{where}.source must be "request" or "suggested".')
        elif item["source"] == "suggested" and item["status"] != "randomized":
            errors.append(f'{where}: a suggested part may only be a dimension to vary (status "randomized"); '
                          "everything else must be what the request says.")
        terms = item.get("terms", [])
        if (not isinstance(terms, list) or len(terms) > max_terms or any(
                not isinstance(term, str) or not term.strip() or len(term) > MAX_TERM for term in terms)):
            errors.append(f"{where}.terms must be at most {max_terms} short words.")
        if "input" in item and (type(item["input"]) is not int or not 1 <= item["input"] <= max(guided, 0)):
            errors.append(f"{where}.input must name one of the {guided} guided inputs." if guided
                          else f"{where}.input is only for guided inputs, and there are none.")
        if "character" in item and (item["kind"] not in FIELD_KINDS["character"] or not isinstance(item["character"], str)
                                    or _label_key(item["character"]) not in labels):
            errors.append(f"{where}.character must be one of the characters labels, on a subject.")
        elif "member" in item and ("character" not in item or type(item["member"]) is not int
                                   or not 1 <= item["member"] <= labels[_label_key(item["character"])]):
            errors.append(f"{where}.member must number one of the people of its character (1 to its count).")
    for number, item in enumerate(elements, 1):
        if not isinstance(item, dict) or item.get("id") not in known or known[item["id"]] is not item:
            continue
        where, scope = f"intent.elements[{number}]", item.get("input", 0)
        links = []
        if "of" in item:
            owner = known.get(item["of"]) if isinstance(item["of"], str) else None
            if item.get("kind") not in FIELD_KINDS["of"]:
                errors.append(f"{where}.of is only for an object, body part or attribute.")
            elif owner is None or owner is item or owner.get("kind") not in OWNERS:
                errors.append(f"{where}.of must be the id of the subject, object or body part it belongs to.")
            else:
                links.append(owner)
        for field in ("by", "to"):
            allowed = FIELD_KINDS[field]
            if field not in item:
                continue
            targets = item[field]
            if item.get("kind") not in allowed:
                errors.append(f"{where}.{field} is only for {' or '.join(allowed)}.")
            elif (not isinstance(targets, list) or not targets or len(targets) > MAX_LINKS
                  or any(not isinstance(target, str) or target not in known or known[target] is item for target in targets)):
                errors.append(f"{where}.{field} must list ids of other parts.")
            elif field == "by" and any(known[target].get("kind") != "subject" for target in targets):
                errors.append(f"{where}.by must list subjects.")
            elif field == "to" and any(known[target].get("kind") in NO_TARGET for target in targets):
                errors.append(f"{where}.to cannot be an attribute or aspect.")
            else:
                links += [known[target] for target in targets]
        if any(link.get("input", 0) not in (0, scope) for link in links):
            errors.append(f"{where} links to a part of another guided input.")
    people = {}  # a person is one part at most; a character has at most as many parts as people
    for item in known.values():
        if item.get("kind") == "subject" and isinstance(item.get("character"), str) and _label_key(item["character"]) in labels:
            people.setdefault(_label_key(item["character"]), []).append(item)
    for key, items in people.items():
        numbers = [item["member"] for item in items if type(item.get("member")) is int]
        if len(numbers) != len(set(numbers)):
            errors.append(f'intent.elements: two subject parts are the same person of "{items[0]["character"]}" (same member).')
        elif len(items) > labels[key]:
            errors.append(f'intent.elements: "{items[0]["character"]}" is {labels[key]} '
                          f'{"person" if labels[key] == 1 else "people"} but has {len(items)} subject parts; give each '
                          "person one part (numbered with member) or the group one part.")
    if cyclic := _ownership_cycles(known):
        errors.append(f"intent.elements: {sorted(cyclic)[0]} belongs to itself through of.")
    for number, item in enumerate(relations, 1):
        where = f"intent.relations[{number}]"
        if not isinstance(item, dict) or set(item) != {"a", "rel", "b", "status"}:
            errors.append(f"{where} needs exactly a, rel, b and status.")
        elif (not isinstance(item["a"], str) or not isinstance(item["b"], str)
              or item["a"] not in known or item["b"] not in known or item["a"] == item["b"]):
            errors.append(f"{where}.a and .b must be ids of two different parts.")
        elif not isinstance(item["rel"], str) or not item["rel"].strip() or len(item["rel"]) > MAX_TEXT:
            errors.append(f"{where}.rel must be the user's words for the link.")
        elif item["status"] not in RELATION_STATUSES:
            errors.append(f"{where}.status must be one of {', '.join(RELATION_STATUSES)}.")
        elif 0 not in (known[item["a"]].get("input", 0), known[item["b"]].get("input", 0)) and \
                known[item["a"]].get("input") != known[item["b"]].get("input"):
            errors.append(f"{where} links parts of two different guided inputs.")
    notes = value.get("unresolved", [])
    if not isinstance(notes, list) or len(notes) > MAX_UNRESOLVED or any(
            not isinstance(note, str) or not note.strip() or len(note) > MAX_NOTE for note in notes):
        errors.append(f"intent.unresolved must be at most {MAX_UNRESOLVED} short notes.")
    if "truncated" in value and type(value["truncated"]) is not bool:
        errors.append("intent.truncated must be true or false.")
    return errors


# ---------------------------------------------------------------- the normalized form

def cast_of(character, characters):
    """The cast labels a character stands for: "man" -> ["man 1", "man 2"] (Understanding numbers identical
    people), "Naruto" -> ["Naruto"]."""
    if not character:
        return []
    key = _label_key(character)
    return [person["label"] for person in characters
            if _label_key(person["label"]) == key or re.sub(r" \d+$", "", _label_key(person["label"])) == key]


def character_labels(characters):
    """What a subject's character may be: a cast label, or one without its number."""
    return sorted({person["label"] for person in characters} | {re.sub(r" \d+$", "", person["label"]) for person in characters})


def character_counts(characters):
    """{label a subject may name: how many people it stands for} for a brief's expanded characters."""
    return {label: len(cast_of(label, characters)) for label in character_labels(characters)}


def person_cast(character, member, characters):
    """The people a subject is: one numbered person ("man", 2 -> ["man 2"]), else everyone its character stands for."""
    cast = cast_of(character, characters)
    if member and len(cast) > 1:
        return [label for label in cast if _label_key(label) == f"{_label_key(character)} {member}"]
    return cast


def _bind(elements, characters):
    """Number unnumbered subject parts when that is structural, not a guess: a group of N people with exactly N
    parts is one part per person, so the parts without a member get the remaining numbers in order. A single
    unnumbered part is the whole group. Anything else stays as given (warnings reports it)."""
    groups = {}
    for item in elements:
        if item["kind"] == "subject" and item["character"]:
            groups.setdefault(item["character"], []).append(item)
    for character, items in groups.items():
        size = len(cast_of(character, characters))
        free = [item for item in items if not item["member"]]
        if size > 1 and len(items) == size and free:
            taken = {item["member"] for item in items}
            for item, number in zip(free, (number for number in range(1, size + 1) if number not in taken)):
                item["member"] = number


def _people_parts(elements, characters):
    """A subject part for every character that has none: who appears is stated (the characters list), so this adds
    no content; it only gives each person a part to link to. One part per character entry, as a group when it
    stands for several identical people. Nothing is added when a subject is not tied to a character: it may be
    those people under another name ("adults"), and a second part for them would be a duplicate."""
    if any(item["kind"] == "subject" and not item["character"] for item in elements):
        return elements
    named = {item["character"] for item in elements if item["kind"] == "subject"}
    taken, added, number = {item["id"] for item in elements}, [], 0
    for character in dict.fromkeys(re.sub(r" \d+$", "", person["label"]) for person in characters):
        if character in named or len(elements) + len(added) >= MAX_ELEMENTS:
            continue
        number += 1
        while f"p{number}" in taken:
            number += 1
        added.append({"id": f"p{number}", "kind": "subject", "text": character, "status": "fixed", "source": "request",
                      "character": character, "member": 0, "of": "", "by": [], "to": [], "input": 0, "terms": []})
    return added + elements


def _duplicates_action(relation, elements):
    """Only the same single actor, target, status, scope and action words; never infer a missing link."""
    parts = {item["id"]: item for item in elements}
    scope = parts[relation["a"]]["input"] or parts[relation["b"]]["input"]
    wording = re.sub(r"^(?:am|is|are)\s+", "", relation["rel"].strip(), flags=re.IGNORECASE)
    actor, target = relation["a"], relation["b"]
    if passive := re.fullmatch(r"(?:am|is|are|was|were)\s+being\s+(.+)\s+by", relation["rel"].strip(), flags=re.IGNORECASE):
        actor, target, wording = target, actor, passive[1]
    return any(item["kind"] == "action" and item["by"] == [actor] and item["to"] == [target]
               and item["status"] == relation["status"] and item["input"] == scope
               and _words(item["text"]) == _words(wording) for item in elements)


def normalize(value, characters, avoid, user_texts, base=lambda label: label, *, notices=()):
    """The model's checked intent in its stored form, with every field present and warnings computed.

    base maps the model's characters label to the cast label it became (understanding.cast_base)."""
    value = prepare(value)

    def character(item):
        return base(item["character"].strip()) if item.get("character", "").strip() else ""
    elements = [{"id": item["id"], "kind": item["kind"], "text": item["text"].strip(), "status": item["status"],
                 "source": item["source"], "character": character(item), "member": item.get("member", 0),
                 "of": item.get("of", ""), "by": list(item.get("by", [])), "to": list(item.get("to", [])),
                 "input": item.get("input", 0), "terms": _unique(term.strip() for term in item.get("terms", []))}
                for item in value["elements"]]
    _bind(elements, characters)
    elements = [{**item, "cast": person_cast(item["character"], item["member"], characters)}
                for item in _people_parts(elements, characters)]
    relations = [item for item in value["relations"] if not _duplicates_action(item, elements)]
    relations = [{"id": f"r{number}", "a": item["a"], "rel": item["rel"].strip(), "b": item["b"], "status": item["status"]}
                 for number, item in enumerate(relations, 1)]
    intent = {"available": True, "elements": elements, "relations": relations,
              "unresolved": [note.strip() for note in value.get("unresolved", [])], "truncated": value.get("truncated", False),
              "warnings": list(notices)}
    intent["warnings"] = warnings(intent, avoid, user_texts)
    return intent


def _unique(terms):
    """Search terms without repeats (case-insensitive), in order."""
    return list({term.casefold(): term for term in reversed([term for term in terms if term])}.values())[::-1]


def unavailable(reason):
    """The intent of a brief whose structured details could not be validated: the brief itself still holds."""
    return {"available": False, "elements": [], "relations": [], "unresolved": [], "truncated": False,
            "warnings": [f"Structured details are unavailable ({reason}). The summary, fixed, must and avoid still apply."]}


def _model_form(intent):
    """A stored intent back in the model's form, for the same contract check."""
    elements = []
    for item in intent["elements"]:
        elements.append(_present({key: item[key] for key in (*REQUIRED, *OPTIONAL) if key in item}))
    return {"elements": elements, "relations": [{key: item[key] for key in ("a", "rel", "b", "status")} for item in intent["relations"]],
            "unresolved": intent["unresolved"], "truncated": intent["truncated"]}


def validate(intent, brief):
    """Raise ValueError unless intent is a valid stored intent for this brief."""
    fields = {"available", "elements", "relations", "unresolved", "truncated", "warnings"}
    if not isinstance(intent, dict) or set(intent) != fields or type(intent["available"]) is not bool:
        raise ValueError(f"intent needs exactly: {', '.join(sorted(fields))}.")
    if not isinstance(intent["warnings"], list) or any(not isinstance(item, str) for item in intent["warnings"]):
        raise ValueError("intent.warnings must be a list of notes.")
    element_fields = set(STORED)
    if (not isinstance(intent["elements"], list) or any(not isinstance(item, dict) or set(item) - {"member"} != element_fields - {"member"}
                                                        or set(item) - element_fields for item in intent["elements"])):
        raise ValueError(f"intent elements need exactly: {', '.join(sorted(element_fields))} (member may be absent).")
    if (not isinstance(intent["relations"], list) or any(not isinstance(item, dict) or set(item) != {"id", "a", "rel", "b", "status"}
                                                         for item in intent["relations"])):
        raise ValueError("intent relations need exactly: id, a, rel, b, status.")
    if not intent["available"] and (intent["elements"] or intent["relations"] or intent["unresolved"]):
        raise ValueError("An unavailable intent has no elements, relations or notes.")
    errors = check(_model_form(intent), character_counts(brief["characters"]), len(brief["input"].get("guided_inputs", [])),
                   max_terms=MAX_REVIEW_TERMS)
    if errors:
        raise ValueError(errors[0])
    for item in intent["elements"]:
        if item["cast"] != person_cast(item["character"], item.get("member", 0), brief["characters"]):
            raise ValueError(f"intent element {item['id']}: cast must be the people its character and member stand for.")
    return intent


def search_hints(brief):
    """Optional search evidence, never requirements or new participant/ownership assignments.

    Only grounded, globally applicable parts of a validated v10 intent participate. Ambiguous or
    incomplete interpretations fall back to the brief; scoped input hints must not leak to other images.
    """
    if brief.get("version") != 10:
        return ()
    try:
        value = validate(brief.get("intent"), brief)
    except (ValueError, KeyError, TypeError):
        return ()
    if not value["available"] or value["unresolved"] or value["truncated"]:
        return ()
    texts = [brief["input"]["request"], *brief["input"].get("rules", []), brief["fixed"],
             brief["randomized"], *brief["must"]]
    positive = {word for text in texts for word in split_negated(text)[0]}

    def grounded(text):
        words, negative = split_negated(text)
        return bool(words) and set(words) <= positive and not negative

    subjects = [item for item in value["elements"] if item["kind"] == "subject"]
    bindings = Counter(label for item in subjects for label in item["cast"])
    usable = {item["id"]: item for item in value["elements"]
              if item["source"] == "request" and item["status"] != "excluded" and not item["input"]
              and (bool(item["cast"]) and all(bindings[label] == 1 for label in item["cast"])
                   if item["kind"] == "subject" else grounded(item["text"]))
              and (item["kind"] not in ("action", "pose") or item["by"])}
    # A usable link must keep all its endpoints, never guess a replacement or silently broaden its scope.
    while missing := {ident for ident, item in usable.items()
                      if any(ref not in usable for ref in [*item["by"], *item["to"], *([item["of"]] if item["of"] else [])])}:
        usable = {ident: item for ident, item in usable.items() if ident not in missing}
    hints = [text for item in usable.values() if item["kind"] != "subject" for text in [item["text"], *item["terms"]]]
    hints += [item["rel"] for item in value["relations"] if item["status"] != "excluded"
              and item["a"] in usable and item["b"] in usable and grounded(item["rel"])]
    return tuple(_unique(hints))


# ---------------------------------------------------------------- warnings

def singular(word):
    """A word with an irregular plural in its singular form ("men" -> "man"); any other word unchanged."""
    return IRREGULAR_PLURALS.get(word.casefold(), word)


def _form(word):
    """The base form of a word for comparing wording: irregular plurals, then the vocabulary's general English
    endings (plural, -ing, -ed): "men" -> "man", "kisses" -> "kiss". Only to compare, never to decide."""
    return stem(singular(word.casefold()))


def _words(text):
    return [_form(word) for word in WORD.findall(str(text).casefold())]


def _content(text):
    """The words that carry meaning: no function words, negations or numbers ("2 men" -> ["man"])."""
    return [_form(word) for word in WORD.findall(str(text).casefold())
            if word not in STOPWORDS and word not in NEGATIONS and word not in NUMBER_WORDS and not word.isdigit()]


def _meets(word, words):
    return any(word == other or (len(word) >= 4 and len(other) >= 4 and (word.startswith(other[:4]) and other.startswith(word[:4])))
               for other in words)


def _within(text, phrase):
    """Every word of text appears in phrase (so "oral" is within "no oral")."""
    words = [word for word in _words(text) if len(word) > 2] or _words(text)
    return bool(words) and all(_meets(word, _words(phrase)) for word in words)


def _overlaps(text, phrase):
    """Some word of text appears in phrase: enough to point out, never to refuse."""
    words = [word for word in _words(phrase) if len(word) > 2]
    return any(_meets(word, words) for word in _words(text) if len(word) > 2)


def warnings(intent, avoid, user_texts):
    """Notes for review, recomputed whenever intent changes. They report; they never rewrite."""
    if not intent["available"]:
        return list(intent["warnings"])
    notes = [note for note in intent["warnings"] if note.startswith(UNAVAILABLE_NOTE)]
    user = _words(" ".join(user_texts))
    for item in intent["elements"]:
        quoted = f'"{item["text"]}"'
        # Only a part every image must show (or must not) matters here, and only when none of its words is in
        # the request: then it may have been added. A paraphrase that shares a word, a plural or a person from
        # the characters list is not doubtful.
        words = _content(item["text"])
        if (item["source"] == "request" and item["status"] in ("fixed", "excluded") and not item["cast"] and words
                and not any(_meets(word, user) for word in words)):
            notes.append(f"{quoted} is {'required in every image' if item['status'] == 'fixed' else 'ruled out'}, but the "
                         "request does not seem to say it; check the analysis did not add it.")
        clash = next((phrase for phrase in avoid if _within(item["text"], phrase)), None)
        if item["status"] != "excluded" and clash:
            notes.append(f'{quoted} is {item["status"]} here, but the request rules out "{clash}"; avoid applies.')
        if item["status"] == "excluded" and not clash:
            notes.append(f"{quoted} is excluded here but not listed under avoid; avoid is what the scenes follow.")
        for term in item["terms"]:
            if phrase := next((phrase for phrase in avoid if _overlaps(term, phrase)), None):
                notes.append(f'The search word "{term}" for {quoted} matches the ruled-out "{phrase}".')
    seen = {}
    for item in intent["elements"]:
        key = " ".join(_words(item["text"]))
        if key in seen and {seen[key], item["status"]} == {"fixed", "excluded"}:
            notes.append(f'"{item["text"]}" is both fixed and excluded.')
        seen.setdefault(key, item["status"])
    for varied in intent["elements"]:
        if varied["status"] != "randomized" or varied["kind"] not in ("attribute", "aspect"):
            continue
        words = _words(varied["text"])
        for fixed in intent["elements"]:
            if fixed["status"] != "fixed" or fixed["kind"] not in ("attribute", "aspect", "environment", "object", "body_part"):
                continue
            if varied["of"] not in (fixed["of"], fixed["id"]):
                continue
            if varied["input"] and fixed["input"] and varied["input"] != fixed["input"]:
                continue
            fixed_words = _words(fixed["text"])
            if words != fixed_words and set(WORD.findall(fixed["text"].casefold())) & NEGATIONS:
                continue
            if words and any(fixed_words[index:index + len(words)] == words for index in range(len(fixed_words) - len(words) + 1)):
                notes.append(f'"{varied["text"]}" is marked randomized but is also fixed in "{fixed["text"]}"; '
                             "the authoritative brief still applies.")
                break
    groups = {}
    for item in intent["elements"]:
        if item["kind"] == "subject" and item["character"] and len(item["cast"]) > 1:
            groups.setdefault(item["character"], []).append(item)
    for character, items in groups.items():
        if len(items) > 1:
            notes.append(f'{len(items)} parts refer to "{character}" ({", ".join(items[0]["cast"])}) without saying which '
                         "person each is; who does what among them is unclear.")
    if intent["truncated"]:
        notes.append("The request has more parts than fit here; the summary, fixed, must and avoid still hold in full.")
    return notes


# ---------------------------------------------------------------- review edits

def reviewed(approved, submitted, brief, user_texts):
    """The intent after review, or ValueError explaining the first edit that is not allowed.

    Allowed: correct links (character, member, of, by, to; a relation's a and b), add, change or remove search terms,
    remove a suggested part, remove an unresolved note. Everything the request states keeps its kind, words,
    status and scope, and is not removed; that is changed with Revise. Warnings and casts are recomputed here,
    never taken from the browser."""
    if submitted == approved:
        return approved
    if not isinstance(submitted, dict) or set(submitted) != set(approved):
        raise ValueError("The structured details are not in the expected form. Reload the review and try again.")
    if not approved["available"]:
        raise ValueError("Structured details are unavailable for this request, so there is nothing to edit.")
    if submitted["truncated"] != approved["truncated"]:
        raise ValueError("Whether the details are complete is decided by the analysis, not edited.")
    before = {item["id"]: item for item in approved["elements"]}
    after = submitted["elements"] if isinstance(submitted["elements"], list) else None
    if after is None or any(not isinstance(item, dict) or item.get("id") not in before for item in after):
        raise ValueError("Parts can be corrected or removed here, not added. Use Revise to add to the request.")
    ids = [item["id"] for item in after]
    if len(ids) != len(set(ids)):
        raise ValueError("Each part can appear only once.")
    for ident in set(before) - set(ids):
        if before[ident]["source"] != "suggested":
            raise ValueError(f'"{before[ident]["text"]}" comes from your request, so it stays. Use Revise to change the request.')
    elements = []
    for item in after:
        old = before[item["id"]]
        if set(item) != set(old):
            raise ValueError("The structured details are not in the expected form. Reload the review and try again.")
        for key in ("kind", "text", "status", "source", "input"):
            if item[key] != old[key]:
                raise ValueError(f'The {key} of "{old["text"]}" is set by your request. Use Revise to change it.')
        terms = item["terms"]
        if not isinstance(terms, list) or len(terms) > MAX_REVIEW_TERMS or any(
                not isinstance(term, str) or not term.strip() or len(term) > MAX_TERM for term in terms):
            raise ValueError(f'Use up to {MAX_REVIEW_TERMS} search words of at most {MAX_TERM} characters for "{old["text"]}".')
        for term in terms:
            if phrase := next((phrase for phrase in brief["avoid"] if _within(term, phrase)), None):
                raise ValueError(f'The search word "{term}" matches "{phrase}", which the request rules out.')
        elements.append({**item, "terms": _unique(term.strip() for term in terms),
                         "cast": person_cast(item["character"], item.get("member", 0), brief["characters"])})
    kept = set(ids)
    relations = submitted["relations"] if isinstance(submitted["relations"], list) else None
    old_relations = {item["id"]: item for item in approved["relations"]}
    if relations is None or [item.get("id") for item in relations if isinstance(item, dict)] != list(old_relations):
        raise ValueError("Links between parts can be corrected here, not added or removed. Use Revise for that.")
    for item in relations:
        old = old_relations[item["id"]]
        if set(item) != set(old) or item["rel"] != old["rel"] or item["status"] != old["status"]:
            raise ValueError(f'The wording and status of the link "{old["rel"]}" are set by your request. Use Revise to change them.')
    notes = submitted["unresolved"]
    if not isinstance(notes, list) or any(note not in approved["unresolved"] for note in notes):
        raise ValueError("Notes on unclear points can be dismissed here, not written.")
    referenced = {target for item in elements for target in (item["of"], *item["by"], *item["to"]) if target} | \
        {end for item in relations for end in (item["a"], item["b"])}
    if missing := referenced - kept:
        raise ValueError(f"A removed part is still linked from another ({', '.join(sorted(missing))}); correct that link first.")
    intent = {"available": True, "elements": elements, "relations": [dict(item) for item in relations],
              "unresolved": list(notes), "truncated": approved["truncated"],
              "warnings": [note for note in approved["warnings"] if note.startswith(UNAVAILABLE_NOTE)]}
    errors = check(_model_form(intent), character_counts(brief["characters"]), len(brief["input"].get("guided_inputs", [])),
                   max_terms=MAX_REVIEW_TERMS)
    if errors:
        raise ValueError(f"That correction does not fit the details: {errors[0]}")
    intent["warnings"] = warnings(intent, brief["avoid"], user_texts)
    return intent
