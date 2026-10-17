"""Confirmation tickets: Confirm runs only the brief Understanding produced for exactly this input."""

from collections import OrderedDict
from copy import deepcopy
import hashlib
import json
import secrets
import threading
import time

from .understanding import validate_brief

# Run-to-run choices that do not change what was understood (Understanding never reads vocabulary).
UNSIGNED = frozenset({"seed", "seed_mode", "vocabulary_packs"})


def intent_signature(data):
    """What a ticket is bound to: the draft without its seed settings and private keys."""
    source = {key: value for key, value in data.items() if key not in UNSIGNED and not key.startswith("_")}
    return hashlib.sha256(json.dumps(source, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


class DatasetIntentTickets:
    """Expiring in-memory tickets, one per analyzed brief."""

    def __init__(self, *, clock=time.monotonic, limit=32, lifetime=3600):
        self.clock, self.limit, self.lifetime = clock, limit, lifetime
        self.items = OrderedDict()
        self.lock = threading.RLock()

    def register(self, data, brief):
        brief = validate_brief(brief)
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
