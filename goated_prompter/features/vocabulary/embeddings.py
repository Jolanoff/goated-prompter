"""Vocabulary embeddings: vectors from a small separate embedding model, for retrieval by meaning (retrieval.py).

The model is a GGUF run by its own llama-server on the CPU (backends/llama_cpp_process.py LlamaCppEmbedder), apart from
the generation model, set by local_llama_cpp.embedding_model_path; without it retrieval works by words alone. Entry and
group texts are embedded once and cached by their text in one file per model, so only new or changed texts are
embedded again; query texts are kept for the run. When the embedder fails, embeddings are off for the rest of the run.
"""

import base64
from array import array
import hashlib
import json
import math

from ...backends.base import GoatedPrompterError
from ...backends.llama_cpp_process import LlamaCppEmbedder, LlamaCppEmbeddingConfig
from ...config import PROJECT_ROOT
from ...json_store import atomic_json

CACHE = PROJECT_ROOT / "data" / "cache" / "vocabulary-embeddings.json"


def dot(left, right):
    return sum(a * b for a, b in zip(left, right))


def unit(vector):
    length = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [value / length for value in vector]


def embeddings_for(config, progress=print, cache_path=None):
    """The run's Embeddings from the backend config's local_llama_cpp embedding_model_path; None without one (words
    still work) or when it cannot be used."""
    try:
        settings = LlamaCppEmbeddingConfig.from_mapping((config or {}).get("local_llama_cpp"))
    except GoatedPrompterError as error:
        progress(f"Vocabulary search by meaning is off ({error}); exact words still work.")
        return None
    return Embeddings(LlamaCppEmbedder(settings), cache_path or CACHE, progress) if settings else None


class Embeddings:
    """Unit vectors from an embedder: documents cached per model by the text's hash, queries kept for the run."""

    def __init__(self, embedder, cache_path, progress=print):
        self.embedder, self.path, self.progress = embedder, cache_path, progress
        self._queries, self._cache, self._vectors, self.failed = {}, None, {}, False

    @staticmethod
    def _key(text):
        return hashlib.sha256(" ".join(str(text).split()).casefold().encode("utf-8")).hexdigest()[:32]

    def _load(self):
        if self._cache is None:
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                self._cache = data["vectors"] if data.get("model") == self.embedder.model_id else {}
            except (OSError, ValueError, KeyError, TypeError, AttributeError):
                self._cache = {}
        return self._cache

    def _embed(self, texts):
        if self.failed:
            return None
        try:
            return [unit(vector) for vector in self.embedder.embed(texts)]
        except (GoatedPrompterError, OSError) as error:
            self.failed = True
            self.progress(f"Vocabulary search by meaning is off for this run ({error}); exact words still work.")
            return None

    def documents(self, texts):
        """One vector per text (None when embedding fails); only texts not in the cache are embedded."""
        cache = self._load()
        missing = list(dict.fromkeys(text for text in texts if self._key(text) not in cache))
        if missing:
            vectors = self._embed(missing)
            if vectors is None:
                return None
            for text, vector in zip(missing, vectors):
                cache[self._key(text)] = base64.b64encode(array("f", vector).tobytes()).decode("ascii")
            atomic_json(self.path, {"model": self.embedder.model_id, "vectors": cache})
        for key in {self._key(text) for text in texts} - set(self._vectors):
            self._vectors[key] = list(array("f", base64.b64decode(cache[key])))
        return [self._vectors[self._key(text)] for text in texts]

    def query(self, text):
        """The vector of one query text, embedded once per run (None when embedding fails)."""
        key = self._key(text)
        if key not in self._queries:
            vectors = self._embed([text])
            if vectors is None:
                return None
            self._queries[key] = vectors[0]
        return self._queries[key]

    def prepare(self, texts):
        """Embed several query texts in one call, so a run asks the model once."""
        missing = [text for text in dict.fromkeys(texts) if text and self._key(text) not in self._queries]
        if missing and (vectors := self._embed(missing)) is not None:
            self._queries.update(zip(map(self._key, missing), vectors))

    def close(self):
        """Stop the embedding server (it starts again on the next embed)."""
        self.embedder.close()
