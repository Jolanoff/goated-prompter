"""Recent Dataset ideas: their text in RAM only, and private fingerprints that survive restarts.

The text of recent ideas is shown to the model during a session and is never written to disk.
Across restarts only fingerprints are kept: each idea's key words, hashed with a random
per-install key and cut to 20 bits, so the file cannot be read back and many different words
share each value. They only let the brainstorm prefer candidates unlike recent runs.
"""

from collections import OrderedDict
import hashlib
import secrets
import threading
import time

from .ideas import MAX_IDEA_CHARACTERS
from .quality import idea_concepts

FINGERPRINT_TTL = 3 * 24 * 3600
FINGERPRINTS_PER_CONCEPT = 300
FINGERPRINT_CONCEPTS = 32
FINGERPRINT_BITS = 20
# Matches the brainstorm's near-repeat threshold.
FINGERPRINT_SIMILARITY = .6


class RecentIdeaHistory:
    def __init__(self, limit=40, concepts=32, ttl=6 * 3600, *, fingerprint_path=None, read=None, write=None):
        self.limit, self.concepts, self.ttl = limit, concepts, ttl
        self._entries = OrderedDict()
        self._lock = threading.RLock()
        self._fingerprint_path, self._read, self._write = fingerprint_path, read, write

    @staticmethod
    def key(data):
        concept = " ".join(data.get("subject", "").casefold().split())
        kind = data.get("trigger_type", "Custom") + "\0" + data.get("custom_type", "").casefold()
        return hashlib.sha256((kind + "\0" + concept).encode()).hexdigest()

    def _expire(self):
        for key, (stamp, _ideas) in list(self._entries.items()):
            if time.monotonic() - stamp > self.ttl:
                del self._entries[key]

    def recent(self, data):
        with self._lock:
            self._expire()
            record = self._entries.get(self.key(data))
            return list(record[1]) if record else []

    def remember(self, data, rows):
        with self._lock:
            self._expire()
            key = self.key(data)
            ideas = self.recent(data)
            seen = {idea.casefold() for idea in ideas}
            for row in rows:
                idea = " ".join(row.get("idea", "").split())[:MAX_IDEA_CHARACTERS]
                if idea and row.get("idea_status") != "failed" and idea.casefold() not in seen:
                    ideas.append(idea)
                    seen.add(idea.casefold())
            if ideas:
                self._entries[key] = (time.monotonic(), ideas[-self.limit:])
                self._entries.move_to_end(key)
            while len(self._entries) > self.concepts:
                self._entries.popitem(last=False)
            self._remember_fingerprints(key, [row["idea"] for row in rows
                                              if row.get("idea") and row.get("idea_status") != "failed"])

    def clear(self):
        """Release all in-memory events when the application shuts down; fingerprints stay."""
        with self._lock:
            self._entries.clear()

    def seen_before(self, data, text):
        """True when ``text`` matches the fingerprint of an idea from a recent run."""
        if self._fingerprint_path is None:
            return False
        with self._lock:
            store = self._load_fingerprints()
            mark = _fingerprint(text, store["key"])
            if not mark:
                return False
            return any(len(mark & set(past)) / len(mark | set(past)) >= FINGERPRINT_SIMILARITY
                       for _stamp, past in store["concepts"].get(self.key(data), ()))

    def _remember_fingerprints(self, key, ideas):
        if self._fingerprint_path is None or not ideas:
            return
        store = self._load_fingerprints()
        rows = store["concepts"].pop(key, [])
        rows.extend([int(time.time()), sorted(mark)] for idea in ideas if (mark := _fingerprint(idea, store["key"])))
        store["concepts"][key] = rows[-FINGERPRINTS_PER_CONCEPT:]
        while len(store["concepts"]) > FINGERPRINT_CONCEPTS:
            store["concepts"].pop(next(iter(store["concepts"])))
        try:
            self._write(self._fingerprint_path, store)
        except (OSError, ValueError):
            pass  # Fingerprints only steer variety; a failed save never blocks generation.

    def _load_fingerprints(self):
        """Read the store, dropping expired fingerprints; an unreadable store starts fresh."""
        try:
            store = self._read(self._fingerprint_path) if self._fingerprint_path.exists() else {}
        except (OSError, ValueError):
            store = {}
        key = store.get("key") if isinstance(store, dict) else None
        if not (isinstance(key, str) and len(key) == 64):
            return {"key": secrets.token_hex(32), "concepts": {}}
        cutoff = time.time() - FINGERPRINT_TTL
        concepts = {}
        for concept, rows in (store.get("concepts") or {}).items():
            kept = [row for row in rows if isinstance(row, list) and len(row) == 2 and isinstance(row[0], int)
                    and row[0] >= cutoff and isinstance(row[1], list) and all(type(item) is int for item in row[1])]
            if isinstance(concept, str) and kept:
                concepts[concept] = kept
        return {"key": key, "concepts": concepts}


def _fingerprint(text, key):
    """Each key word hashed with the install key and cut to FINGERPRINT_BITS bits."""
    secret = bytes.fromhex(key)
    return {int.from_bytes(hashlib.blake2b(word.encode(), key=secret, digest_size=4).digest(), "big")
            >> (32 - FINGERPRINT_BITS) for word in idea_concepts(str(text or ""))}
