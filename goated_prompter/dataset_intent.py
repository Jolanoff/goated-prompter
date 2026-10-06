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
               if key not in {"results", "result_job_id"} and not key.startswith("_")}
    return hashlib.sha256(json.dumps(source, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")).encode()).hexdigest()


class DatasetIntentTickets:
    """RAM-only tickets expire on restart, edits, or after one hour."""

    def __init__(self, *, clock=time.monotonic, limit=32, lifetime=3600):
        self.clock, self.limit, self.lifetime = clock, limit, lifetime
        self.items = OrderedDict()
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
