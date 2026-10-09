"""Bounded RAM-only event history for Ideas; never saved scenes or prompts."""

from collections import OrderedDict
import hashlib
import threading
import time

from .dataset_ideas import MAX_FIELD_CHARACTERS


class RecentIdeaHistory:
    def __init__(self, limit=40, concepts=32, ttl=6 * 3600):
        self.limit, self.concepts, self.ttl = limit, concepts, ttl
        self._entries = OrderedDict()
        self._lock = threading.RLock()

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
                idea = " ".join(row.get("idea", "").split())[:MAX_FIELD_CHARACTERS]
                if idea and row.get("idea_status") != "failed" and idea.casefold() not in seen:
                    ideas.append(idea)
                    seen.add(idea.casefold())
            if ideas:
                self._entries[key] = (time.monotonic(), ideas[-self.limit:])
                self._entries.move_to_end(key)
            while len(self._entries) > self.concepts:
                self._entries.popitem(last=False)

    def clear(self):
        """Release all in-memory events when the application shuts down."""
        with self._lock:
            self._entries.clear()
