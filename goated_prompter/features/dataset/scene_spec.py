"""Immutable, serializable per-image authority for Dataset generation."""

from dataclasses import asdict, dataclass
import hashlib
import json
import re
from ...options.dataset import ANATOMY_KINDS, BODIED_KINDS, SUBJECT_KINDS


POSE_SUPPORTS = {
    "standing": {"feet_on_floor"}, "seated": {"supported_by_chair", "supported_by_bed", "supported_by_floor"},
    "kneeling": {"knees_on_floor", "supported_by_bed"},
    "lying": {"supported_by_bed", "supported_by_floor"},
}
LOCATIONS = {"left", "right", "center", "foreground", "background"}
PARTICIPANT_TEXT_LIMIT = 240
CONTACT_PART_LIMIT = 80
CONTACT_PART_PATTERN = r"[a-z]+(_[a-z]+)*"
BODY_PARTS = {"left_hand", "right_hand", "hand", "shoulder", "waist", "back", "arm", "mouth", "feet",
              "hips", "torso", "genitals", "penis", "vagina", "anus", "paw", "paws", "tail", "wing"}
PLANNING_CATEGORIES = frozenset({"general", "paired_pose", "solo", "group_pose", "oral", "anal", "vaginal", "feet",
                                "toys", "finish", "kink", "pet", "furniture", "aftercare"})


def valid_part_id(value):
    """Owned part names are normalized identifiers; applicable validators decide their physical meaning."""
    return isinstance(value, str) and len(value) <= CONTACT_PART_LIMIT and bool(re.fullmatch(CONTACT_PART_PATTERN, value))


def validate_planning_constraints(values, scopes, count, *, subject_kinds=None):
    """Understanding records only supplied mechanics; null means the app may choose later."""
    if not isinstance(values, list) or len(values) > 24:
        raise ValueError("Planning constraints must be a scoped array.")
    result = []
    for value in values:
        if (not isinstance(value, dict) or set(value) != {"scope", "action", "setting", "participants", "contacts"}
                or value["scope"] not in scopes):
            raise ValueError("Invalid scoped planning constraint fields.")
        for field in ("action", "setting"):
            if value[field] is not None:
                compact_text(value[field], field, resolved=True)
        participants = value["participants"]
        kinds = (subject_kinds or {}).get(value["scope"], {})
        if not isinstance(participants, list) or len(participants) > 100:
            raise ValueError("Invalid planning participant constraints.")
        owners = []
        for item in participants:
            if not isinstance(item, dict) or set(item) != {"id", "role", "pose", "location", "support"}:
                raise ValueError("Planning participant constraints need id, role, pose, location and support.")
            if not isinstance(item["id"], str) or not re.fullmatch(r"P[1-9][0-9]?|P100", item["id"]):
                raise ValueError("Planning owner must reference the expanded cast in user order (P1, P2, ...).")
            if kinds and item["id"] not in kinds or type(count) is int and int(item["id"][1:]) > count:
                raise ValueError("Planning owner exceeds the approved per-image cast.")
            owners.append(item["id"])
            for field in ("pose", "location", "support"):
                if item[field] is not None and (not isinstance(item[field], str) or not item[field].strip() or len(item[field]) > PARTICIPANT_TEXT_LIMIT):
                    raise ValueError(f"Unresolved planning {field}.")
                if item[field] is not None:
                    compact_text(item[field], f"Planning {field}", limit=PARTICIPANT_TEXT_LIMIT, resolved=True)
            if item["location"] is not None and item["location"] not in LOCATIONS:
                raise ValueError("Unresolved planning location.")
            if item["role"] is not None:
                compact_text(item["role"], "Planning role", limit=PARTICIPANT_TEXT_LIMIT, resolved=True)
            if (kinds.get(item["id"]) != "animal" and item["pose"] in POSE_SUPPORTS and item["support"]
                    and item["support"] in {support for supports in POSE_SUPPORTS.values() for support in supports}
                    and item["support"] not in POSE_SUPPORTS[item["pose"]]):
                raise ValueError("Supplied planning pose conflicts with its physical support.")
        if len(owners) != len(set(owners)):
            raise ValueError("Planning constraints repeat a participant owner.")
        if not isinstance(value["contacts"], list) or len(value["contacts"]) > 100:
            raise ValueError("Invalid planning contacts.")
        for contact in value["contacts"]:
            if not isinstance(contact, dict) or set(contact) != {"source", "target"}:
                raise ValueError("Planning contacts require owned source and target.")
            for endpoint in contact.values():
                if not isinstance(endpoint, str):
                    raise ValueError("Invalid planning contact endpoint.")
                owner, _, part = endpoint.partition(".")
                if not re.fullmatch(r"P[1-9][0-9]?|P100", owner) or not valid_part_id(part) or type(count) is int and int(owner[1:]) > count:
                    raise ValueError("Planning contact references an unknown owner or body part.")
        result.append(value)
    return result


def compact_text(value, label, *, limit=1000, resolved=False):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f"{label} must be nonempty text of at most {limit} characters.")
    compact = " ".join(value.split())
    if resolved and compact.casefold() == "unknown":
        raise ValueError(f"{label} is unresolved; leave an unspecified field open instead.")
    return compact


@dataclass(frozen=True)
class Participant:
    id: str
    name: str
    role: str
    pose: str
    location: str
    support: str
    sex: str = "unspecified"
    traits: str = ""
    kind: str = "human"

    @property
    def bodied(self):
        return self.kind in BODIED_KINDS

    @property
    def anatomy(self):
        return self.kind in ANATOMY_KINDS

    @classmethod
    def from_dict(cls, value):
        if (not isinstance(value, dict) or value.keys() - cls.__dataclass_fields__.keys()
                or not {"id", "name", "role", "pose", "location", "support"} <= value.keys()):
            raise ValueError("Invalid SceneSpec participant fields.")
        participant = cls(**value)
        for field in ("id", "name"):
            compact_text(getattr(participant, field), f"Participant {field}", limit=240)
        if not isinstance(participant.role, str) or len(participant.role) > PARTICIPANT_TEXT_LIMIT:
            raise ValueError("Subject role must be compact text or left open.")
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", participant.id):
            raise ValueError("Participant ids must be stable single owner identifiers.")
        if not isinstance(participant.kind, str) or participant.kind not in SUBJECT_KINDS:
            raise ValueError("Unknown SceneSpec subject kind.")
        if not isinstance(participant.pose, str) or not isinstance(participant.support, str):
            raise ValueError("Subject pose and support must be text or empty when not applicable.")
        if not participant.bodied and (participant.pose or participant.support):
            raise ValueError("Non-bodied subjects do not take participant poses or anatomy support.")
        if len(participant.pose) > PARTICIPANT_TEXT_LIMIT or len(participant.support) > PARTICIPANT_TEXT_LIMIT:
            raise ValueError("Subject pose and support must be compact.")
        for field in ("role", "pose", "support"):
            if getattr(participant, field):
                compact_text(getattr(participant, field), f"Subject {field}", limit=PARTICIPANT_TEXT_LIMIT, resolved=True)
        if (participant.kind != "animal" and participant.pose in POSE_SUPPORTS
                and participant.support in {support for supports in POSE_SUPPORTS.values() for support in supports}
                and participant.support not in POSE_SUPPORTS[participant.pose]):
            raise ValueError("Participant pose and physical support are incompatible or unresolved.")
        if (not isinstance(participant.location, str) or not isinstance(participant.sex, str)
                or participant.location not in LOCATIONS | {""} or participant.sex not in {"male", "female", "unspecified", "none"}):
            raise ValueError("Invalid participant location or sex.")
        if not isinstance(participant.traits, str) or len(participant.traits) > 1000:
            raise ValueError("Invalid participant traits.")
        return participant


@dataclass(frozen=True)
class Contact:
    source: str
    target: str


def resolve_supports(participants, relationships=(), *, require_resolved=False):
    """Resolve load-bearing ownership and cycles; this is not a geometry simulator."""
    owners = {item.id: item for item in participants}
    result = list(relationships)
    if len(result) > 100 or any(not isinstance(edge.source, str) or not isinstance(edge.target, str) for edge in result):
        raise ValueError("Support endpoints require bounded owned identifiers.")
    for item in participants:
        if not item.bodied or not item.pose and not item.support:
            continue
        existing = [edge for edge in result if edge.source.split(".")[0] == item.id]
        normalized = {"feet_on_floor": ("feet", "floor"), "knees_on_floor": ("knees", "floor"),
                      "supported_by_chair": ("body", "chair"), "supported_by_bed": ("body", "bed"),
                      "supported_by_floor": ("body", "floor"), "ground": ("body", "ground"),
                      "four_paws_on_ground": ("paws", "ground"), "three_paws_on_ground": ("paws", "ground")}
        if item.support in normalized:
            part, surface = normalized[item.support]
            target = "setting." + surface
        elif re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*\.[a-z]+(?:_[a-z]+)*", item.support):
            part, target = "body", item.support
        elif match := re.fullmatch(r"supported_at_([a-z_]+)_by_([A-Za-z][A-Za-z0-9_-]*)", item.support):
            part, target = match[1], match[2] + ".body"
        elif existing:
            if require_resolved and not item.support:
                raise ValueError("A support relationship needs an explicit participant support label.")
            continue
        else:
            if require_resolved:
                raise ValueError("Selected bodily mechanics need resolved owned support, not unspecified surface prose.")
            continue
        if existing:
            if require_resolved and any(edge.target != target for edge in existing):
                raise ValueError("Owned support contradicts the participant support label.")
        else:
            result.append(Contact(item.id + "." + part, target))
    if len(result) > 100 or len(set(result)) != len(result):
        raise ValueError("Support relationships must be bounded and distinct.")
    if not require_resolved:
        return tuple(result)
    graph = {}
    for edge in result:
        if not isinstance(edge.source, str) or not isinstance(edge.target, str):
            raise ValueError("Support endpoints require owned identifiers.")
        source, _, part = edge.source.partition(".")
        target, _, surface = edge.target.partition(".")
        if source not in owners or not valid_part_id(part) or not valid_part_id(surface):
            raise ValueError("Support references an unresolved owner or surface.")
        if target != "setting" and target not in owners:
            raise ValueError("Support references an unknown supporting owner.")
        if source == target:
            raise ValueError("A subject cannot provide its own weight-bearing support.")
        if owners[source].kind in {"style", "text", "concept"} or target in owners and owners[target].kind in {"style", "text", "concept"}:
            raise ValueError("Nonphysical subjects cannot bear physical support relationships.")
        if owners[source].kind == "human" and part in {"paw", "paws", "tail", "wing"}:
            raise ValueError("Human support references nonhuman anatomy.")
        if target == "setting" and surface in BODY_PARTS | {"body", "head", "foot", "knees"}:
            raise ValueError("Background support must identify a physical surface, not unowned anatomy.")
        if (owners[source].kind == "human" and owners[source].pose == "standing"
                and part not in {"body", "feet", "foot", "left_foot", "right_foot"}):
            raise ValueError("Standing human support must bear weight through the feet.")
        graph.setdefault(source, set()).add(target)
    visited = set()
    def visit(owner, path):
        if owner in path:
            raise ValueError("Supporting owners form an unresolved load-bearing cycle.")
        if owner in visited:
            return
        for target in graph.get(owner, ()):
            visit(target, path | {owner})
        visited.add(owner)
    for owner in graph:
        visit(owner, set())
    return tuple(result)


def validate_scene_mechanics(spec):
    """Generation readiness is separate from decoding historical saved specifications."""
    resolve_supports(spec.participants, spec.supports, require_resolved=True)
    owners = {item.id: item for item in spec.participants}
    for contact in spec.contacts:
        if contact.source == contact.target:
            raise ValueError("A contact cannot connect an endpoint to itself.")
        for endpoint in (contact.source, contact.target):
            owner, part = endpoint.split(".")
            subject = owners[owner]
            if subject.kind in {"style", "text", "concept"}:
                raise ValueError("Nonphysical subjects cannot own physical contacts.")
            if subject.kind == "human" and part in {"paw", "paws", "wing", "tail"}:
                raise ValueError("Human contact references nonhuman anatomy.")


@dataclass(frozen=True)
class SceneSpec:
    index: int
    route: str
    action: str
    participants: tuple[Participant, ...]
    contacts: tuple[Contact, ...] = ()
    setting: str = ""
    hard: tuple[str, ...] = ()
    choices: tuple[tuple[str, str], ...] = ()
    catalog_id: str = ""
    locked: tuple[str, ...] = ("action", "participants", "contacts", "hard")
    version: int = 1
    category: str = "general"
    state: str = "frozen"
    private_vocabulary: bool = False
    concept: str = ""
    supports: tuple[Contact, ...] = ()

    @property
    def required_contacts(self):
        return tuple(contact for contact in self.contacts if "contacts" in self.locked
                     or f"contact:{contact.source}->{contact.target}" in self.locked)

    def to_dict(self):
        return {**asdict(self), "participants": [asdict(item) for item in self.participants],
                "contacts": [asdict(item) for item in self.contacts], "hard": list(self.hard),
                "choices": dict(self.choices), "locked": list(self.locked),
                "supports": [asdict(item) for item in resolve_supports(self.participants, self.supports)]}

    @property
    def signature(self):
        return hashlib.sha256(json.dumps(self.to_dict(), sort_keys=True, ensure_ascii=False,
                                        separators=(",", ":")).encode()).hexdigest()

    @classmethod
    def from_dict(cls, value):
        optional = {"state", "private_vocabulary", "concept", "supports"}
        if not isinstance(value, dict) or set(value) - optional != set(cls.__dataclass_fields__) - optional:
            raise ValueError("SceneSpec requires exactly its versioned planning fields.")
        if (type(value["index"]) is not int or not 1 <= value["index"] <= 25
                or type(value["version"]) is not int or value["version"] != 1):
            raise ValueError("Invalid SceneSpec index or version.")
        if not isinstance(value["route"], str) or value["route"] not in {"general", "adult"}:
            raise ValueError("Invalid SceneSpec content route.")
        if not isinstance(value["category"], str) or value["category"] not in PLANNING_CATEGORIES:
            raise ValueError("Invalid SceneSpec arrangement category.")
        if (not isinstance(value.get("state", "frozen"), str) or value.get("state", "frozen") not in {"provisional", "frozen"}
                or type(value.get("private_vocabulary", False)) is not bool):
            raise ValueError("Invalid SceneSpec state or vocabulary provenance.")
        if not isinstance(value.get("concept", ""), str) or len(value.get("concept", "")) > 10000:
            raise ValueError("SceneSpec concept must be bounded text.")
        compact_text(value["action"], "SceneSpec action", limit=10000, resolved=True)
        if not isinstance(value["participants"], list) or len(value["participants"]) > 100:
            raise ValueError("Invalid SceneSpec cast.")
        participants = tuple(Participant.from_dict(item) for item in value["participants"])
        ids = [item.id for item in participants]
        if len(ids) != len(set(ids)) or len({item.name.casefold() for item in participants}) != len(ids):
            raise ValueError("SceneSpec participant identities must be distinct.")
        contacts = []
        if not isinstance(value["contacts"], list) or len(value["contacts"]) > 100:
            raise ValueError("Invalid SceneSpec contacts.")
        for item in value["contacts"]:
            if not isinstance(item, dict) or set(item) != {"source", "target"}:
                raise ValueError("Contacts require source and target body parts.")
            for endpoint in item.values():
                if not isinstance(endpoint, str):
                    raise ValueError("Contact endpoints must name an owner and a body part.")
                owner, separator, part = endpoint.partition(".")
                subject = next((participant for participant in participants if participant.id == owner), None)
                if not separator or subject is None or not valid_part_id(part):
                    raise ValueError("Contact references an unknown owner or body part.")
            contacts.append(Contact(**item))
        if len(set(contacts)) != len(contacts):
            raise ValueError("SceneSpec contacts must be distinct.")
        supports = value.get("supports", [])
        if not isinstance(supports, list) or any(not isinstance(item, dict) or set(item) != {"source", "target"} for item in supports):
            raise ValueError("Support relationships require owned source and target endpoints.")
        supports = tuple(Contact(**item) for item in supports)
        # Historical frozen plans predate owned support; readability is not readiness.
        supports = resolve_supports(participants, supports)
        for field in ("setting", "catalog_id"):
            if not isinstance(value[field], str) or len(value[field]) > 1000:
                raise ValueError(f"Invalid SceneSpec {field}.")
        if value["setting"]:
            compact_text(value["setting"], "SceneSpec setting", resolved=True)
        if not isinstance(value["hard"], list) or len(value["hard"]) > 100:
            raise ValueError("Invalid SceneSpec requirements.")
        hard = tuple(compact_text(item, "SceneSpec requirement", limit=10000) for item in value["hard"])
        choices = value["choices"]
        if not isinstance(choices, dict) or len(choices) > 20:
            raise ValueError("Invalid SceneSpec creative choices.")
        for key, item in choices.items():
            compact_text(key, "Choice name", limit=80)
            compact_text(item, "Choice value", limit=1000)
        locked = value["locked"]
        allowed_locks = {"action", "participants", "contacts", "hard", "setting",
                         *(f"contact:{contact.source}->{contact.target}" for contact in contacts),
                         *(f"participant:{owner}:{field}" for owner in ids for field in ("role", "pose", "location", "support"))}
        if (not isinstance(locked, list) or any(not isinstance(item, str) for item in locked) or set(locked) - allowed_locks
                or "hard" not in locked):
            raise ValueError("Invalid SceneSpec requirement locks.")
        return cls(value["index"], value["route"], value["action"], participants, tuple(contacts), value["setting"],
                   hard, tuple(choices.items()), value["catalog_id"], tuple(locked), value["version"], value["category"],
                    value.get("state", "frozen"), value.get("private_vocabulary", False), value.get("concept", ""), supports)
