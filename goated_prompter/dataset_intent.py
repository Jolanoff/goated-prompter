"""Source-bound approval tickets for the current Dataset understanding brief."""

from collections import OrderedDict
from copy import deepcopy
import hashlib
import json
import secrets
import threading
import time

from .dataset_understanding import understanding_instruction, validate_understanding


def intent_signature(data):
    source = {key: value for key, value in data.items()
               if key not in {"results", "result_job_id", "plan_scenes_first"} and not key.startswith("_")}
    if "scene_plan" in source:
        source["scene_plan"] = [{key: value for key, value in row.items()
            if key != "prompt_status" and not (row.get("failure_stage") == "prompt"
                and key in {"failure_stage", "failure_reason"})} for row in source["scene_plan"]]
    return hashlib.sha256(json.dumps(source, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")).encode()).hexdigest()


def intent_source_signature(data):
    return intent_signature({key: value for key, value in data.items()
                             if key not in {"scene_plan", "scene_plan_signature"}})


class DatasetIntentTickets:
    """Expiring RAM tickets; durable saved-plan approval lives with its checkpoint."""

    def __init__(self, *, clock=time.monotonic, limit=32, lifetime=3600):
        self.clock, self.limit, self.lifetime = clock, limit, lifetime
        self.items = OrderedDict()
        self.continuations = OrderedDict()
        self.lock = threading.RLock()

    def register(self, data, brief):
        scopes = tuple(json.loads(understanding_instruction(data).user_message)["scopes"])
        brief = validate_understanding(brief, scopes)
        if brief["clarifications"]:
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

    def remember_generated(self, data, brief):
        """Retain approved source intent; generated scene edits still need a check."""
        with self.lock:
            signature = intent_source_signature(data)
            token = self.continuation_token(data)
            if not token or self.items[token][2] != brief:
                token = self.register(data, brief)["confirmation_token"]
            if token:
                self.continuations[signature] = token
                self.continuations.move_to_end(signature)
                while len(self.continuations) > self.limit:
                    self.continuations.popitem(last=False)

    def continuation_token(self, data):
        with self.lock:
            source = intent_source_signature(data)
            token = self.continuations.get(source)
            item = self.items.get(token)
            if not item or self.clock() - item[0] >= self.lifetime:
                return ""
            if item[1] != intent_signature(data):
                # Bind a fresh ticket to the current scene edits, not fresh authority
                # over the user's source. Reads/rebinding never extend its lifetime.
                token = self.register(data, item[2])["confirmation_token"]
                self.items[token] = (item[0], intent_signature(data), deepcopy(item[2]))
                self.continuations[source] = token
            return token
