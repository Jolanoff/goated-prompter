"""Source-bound approval tickets and the confirmed Dataset handoff contract."""

from collections import OrderedDict
from copy import deepcopy
import hashlib
import json
import secrets
import threading
import time

from .dataset_understanding import understanding_instruction, validate_understanding


INTENT_CONTRACT = """CONFIRMED DATASET BRIEF
confirmed_intent is the user's approved interpretation, not hidden reasoning.
For an understanding brief, preserve requested_generation, fixed, rules,
visible_evidence, interactions and visibility_to_preserve. may_vary is permission;
must_vary is required diversity. natural_occlusions must not be removed to expose
every surface. Respect expansion_freedom and dataset_contents. Requirements scoped
all_outputs apply to each image; dataset applies across the set; guided:N applies
only to that original guided input, including when it cycles. Never promote local
requirements into global rules. Compatible conflict resolutions are approaches,
not verified geometry or permission to weaken an explicit requirement.
character_count and identity_policy summarize the interpretation; scoped identity
and count requirements remain authoritative, especially for mixed guided inputs.
Scoped action_options are supplied alternatives, not new actions to invent or a
checklist to combine into the accepted scene. Preserve the chosen event downstream.
For a legacy brief, preserve its goal, count, required rules and fixed identity facts.
Original explicit source requirements remain authoritative; never silently discard them.
For random_per_prompt identities, invent distinct compatible people for each independent
assignment, preserving all specified traits. Keep each person's identity and trigger
role unchanged from idea through scene through final prompt within that assignment.
For fixed identities, preserve supplied identity facts; do not randomize them.
Action options are alternatives across assignments, not a checklist to combine in
one image, unless the user explicitly requires the combination. Describe one frozen
moment. Creative freedoms never override requirements. Guided anchors stay local."""

def validate_intent(value):
    lists = {"fixed_identity_facts", "required_rules", "allowed_variation", "action_options", "blocking_questions"}
    if not isinstance(value, dict) or set(value) != lists | {"goal", "character_count", "identity_policy"}:
        raise ValueError("Request understanding must contain exactly the expected summary fields.")
    def text(item):
        if not isinstance(item, str) or not item.strip() or len(item) > 2000:
            raise ValueError("Summary entries must be nonempty strings of at most 2000 characters.")
        return item.strip()
    result = {"goal": text(value["goal"]), "character_count": value["character_count"],
              "identity_policy": value["identity_policy"]}
    count = result["character_count"]
    if count is not None and (type(count) is not int or not 1 <= count <= 100):
        raise ValueError("Character count must be a positive integer or null.")
    if result["identity_policy"] not in ("fixed", "random_per_prompt", "not_applicable"):
        raise ValueError("Unknown identity policy.")
    for key in lists:
        if not isinstance(value[key], list) or len(value[key]) > 20:
            raise ValueError("Summary lists may contain at most 20 entries.")
        result[key] = [text(item) for item in value[key]]
    return result


def intent_signature(data):
    source = {key: value for key, value in data.items()
              if key not in {"results", "result_job_id", "quality_report"} and not key.startswith("_")}
    return hashlib.sha256(json.dumps(source, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")).encode()).hexdigest()


class DatasetIntentTickets:
    """RAM-only tickets expire on restart, edits, or after one hour."""

    def __init__(self, *, clock=time.monotonic, limit=32, lifetime=3600):
        self.clock, self.limit, self.lifetime = clock, limit, lifetime
        self.items = OrderedDict()
        self.lock = threading.RLock()

    def register(self, data, brief):
        if isinstance(brief, dict) and "requested_generation" in brief:
            scopes = tuple(json.loads(understanding_instruction(data).user_message)["scopes"])
            brief = validate_understanding(brief, scopes)
            questions = brief["clarifications"]
        else:
            brief = validate_intent(brief)
            questions = brief["blocking_questions"]
        if questions:
            return {"brief": brief, "confirmation_token": ""}
        with self.lock:
            token = secrets.token_urlsafe(32)
            self.items[token] = (self.clock(), intent_signature(data), deepcopy(brief))
            while len(self.items) > self.limit:
                self.items.popitem(last=False)
        return {"brief": brief, "confirmation_token": token}

    def approve(self, token, data):
        with self.lock:
            item = self.items.get(token) if isinstance(token, str) else None
            if item is None or self.clock() - item[0] >= self.lifetime:
                raise ValueError("Review and confirm the Dataset request before generating. Approval expired or is missing.")
            if item[1] != intent_signature(data):
                raise ValueError("Dataset input changed after analysis. Review the updated request before generating.")
            return deepcopy(item[2])
