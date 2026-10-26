"""The shared vocabulary retrieval (features/vocabulary/retrieval.py): exact words, meaning with a scripted embedder,
the embedding cache and the spread deal. No model process runs."""

import random
import shutil
import tempfile
import unittest
from pathlib import Path

from goated_prompter.backends.base import BackendGenerationError
from goated_prompter.backends.llama_cpp_process import LlamaCppEmbeddingConfig
from goated_prompter.features.vocabulary import embeddings as vectors_module, retrieval, selection


def group(name, words=(), entries=None, worlds=None, adult=False, selected=False):
    return {"name": name, "words": [name, *words], "entries": list(entries or [f"{name} with a window"]),
            "worlds": worlds, "adult": adult, "selected": selected}


class Embedder:
    """Scripted vectors by text (unknown texts point nowhere in particular); counts the texts it embeds."""

    model_id = "scripted:1"

    def __init__(self, vectors, broken=False):
        self.vectors, self.broken, self.embedded, self.closed = vectors, broken, [], False

    def embed(self, texts):
        if self.broken:
            raise BackendGenerationError("no server")
        self.embedded.append(list(texts))
        return [self.vectors.get(text, [.1, .1, .1]) for text in texts]

    def close(self):
        self.closed = True


class ExactWords(unittest.TestCase):
    def test_words_are_said_whole_and_a_longer_word_wins(self):
        pool = [group("lake", ["water", "lakeside"]), group("aquarium", ["water aquarium"]), group("bedroom", ["his room"])]
        self.assertEqual(retrieval.exact_hits(pool, "a mermaid in a water aquarium"), {1: 1},
                         "water inside water aquarium does not count for the lake")
        self.assertEqual(retrieval.exact_hits(pool, "by the water"), {0: 1})
        self.assertEqual(retrieval.exact_hits(pool, "in her room"), {})
        self.assertEqual(retrieval.exact_hits(pool, "two lakes and a lakeside"), {0: 2}, "a plural ending aside")
        self.assertEqual([row["name"] for row in retrieval.exact_search(pool, "his room by the lake")], ["lake", "bedroom"])
        self.assertEqual(retrieval.exact_search(pool, "a spaceship"), [])

    def test_a_name_the_text_says_narrows_its_group(self):
        lobby = [group("lobby", entries=["hotel lobby with a desk", "elevator with steel walls"])]
        self.assertEqual(retrieval.narrowed(lobby, "in an elevator")[0]["entries"], ["elevator with steel walls"])
        self.assertEqual(retrieval.narrowed(lobby, "in the lobby"), lobby, "only a whole name narrows")
        self.assertEqual(retrieval.entry_name("attic bedroom with a round window"), "attic bedroom")

    def test_groups_come_from_the_selected_packs_first_and_list_an_entry_once(self):
        catalog = {"packs": [{"id": "data/Spaces/Mine", "category": "Spaces", "entries": ["my bedroom", "a rooftop"]},
                             {"id": "Spaces/Everyday-Places", "category": "Spaces", "always": True,
                              "entries": ["my bedroom", "a park"],
                              "groups": [{"name": "park", "words": ["outside"], "worlds": ["everyday"],
                                          "entries": ["my bedroom", "a park"]}]},
                             {"id": "Objects/Tools", "category": "Objects & Props", "always": True, "entries": ["a hammer"]}]}
        rows = retrieval.groups_of(catalog, "Spaces", {"packs": ["data/Spaces/Mine"]})
        self.assertEqual([(row["name"], row["entries"], row["selected"], row["worlds"]) for row in rows],
                         [("my bedroom", ["my bedroom"], True, None), ("a rooftop", ["a rooftop"], True, None),
                          ("park", ["a park"], False, ("everyday",))])
        self.assertEqual(rows[2]["words"], ["park", "outside"])
        self.assertEqual([row["name"] for row in retrieval.groups_of(catalog, "Spaces", {"packs": []})], ["park"])


class Meaning(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.pool = [group("bedroom"), group("kitchen"), group("beach")]
        self.vectors = {retrieval.group_text(self.pool[0]): [1, 0, 0], retrieval.group_text(self.pool[1]): [0, 1, 0],
                        retrieval.group_text(self.pool[2]): [0, 0, 1], "a sleeping chamber": [.95, .1, 0],
                        "somewhere": [.6, .58, 0]}

    def embeddings(self, embedder=None):
        return vectors_module.Embeddings(embedder or Embedder(self.vectors), self.folder / "cache.json", progress=lambda _: None)

    def test_meaning_ranks_the_groups_against_each_other(self):
        embeddings = self.embeddings()
        closeness = retrieval.meaning_scores(self.pool, "a sleeping chamber", embeddings)
        self.assertEqual(closeness.index(max(closeness)), 0)
        scores = retrieval.relevance(self.pool, "a sleeping chamber", embeddings)
        self.assertEqual(scores.index(max(scores)), 0)
        self.assertAlmostEqual(sum(scores), 0.0, places=5, msg="compared with the other groups: z-scores")
        self.assertIsNone(retrieval.meaning_scores(self.pool, "a sleeping chamber", None), "no embeddings, no meaning")

    def test_texts_are_embedded_once_and_again_only_when_they_change(self):
        embedder = Embedder(self.vectors)
        embeddings = self.embeddings(embedder)
        texts = [retrieval.group_text(row) for row in self.pool]
        first = embeddings.documents(texts)
        self.assertEqual(embeddings.documents(texts), first)
        self.assertEqual(len(embedder.embedded), 1)
        again = self.embeddings(Embedder(self.vectors))  # a later run reads the cache file
        again.documents(texts)
        self.assertEqual(again.embedder.embedded, [])
        again.documents([*texts, "a new place"])
        self.assertEqual(again.embedder.embedded, [["a new place"]], "only the new text")
        other = Embedder(self.vectors)
        other.model_id = "scripted:2"
        self.embeddings(other).documents(texts)
        self.assertEqual(len(other.embedded[0]), 3, "another model embeds everything again")
        self.assertAlmostEqual(sum(value * value for value in first[0]), 1.0, places=5, msg="unit length")

    def test_queries_are_embedded_once_per_run_and_together(self):
        embedder = Embedder(self.vectors)
        embeddings = self.embeddings(embedder)
        embeddings.prepare(["a sleeping chamber", "somewhere", ""])
        embeddings.query("a sleeping chamber")
        embeddings.query("somewhere")
        self.assertEqual(embedder.embedded, [["a sleeping chamber", "somewhere"]])
        embeddings.close()
        self.assertTrue(embedder.closed)

    def test_a_failing_embedder_turns_meaning_off_for_the_run(self):
        notes = []
        embeddings = vectors_module.Embeddings(Embedder({}, broken=True), self.folder / "cache.json", progress=notes.append)
        self.assertIsNone(embeddings.query("a sleeping chamber"))
        self.assertIsNone(retrieval.meaning_scores(self.pool, "a sleeping chamber", embeddings))
        self.assertEqual(retrieval.relevance(self.pool, "a sleeping chamber", embeddings),
                         retrieval.word_scores(self.pool, "a sleeping chamber"), "words alone")
        self.assertTrue(embeddings.failed)
        self.assertEqual(len(notes), 1)

    def test_the_embedding_model_comes_from_the_llama_settings(self):
        self.assertIsNone(vectors_module.embeddings_for({"backend": "mock"}))
        notes = []
        self.assertIsNone(vectors_module.embeddings_for(
            {"local_llama_cpp": {"embedding_model_path": str(self.folder / "missing.gguf"),
                                 "llama_server": str(self.folder / "server.exe")}}, notes.append))
        self.assertEqual(len(notes), 1)
        self.assertIsNone(LlamaCppEmbeddingConfig.from_mapping({"model_path": "a.gguf"}), "no embedding model")


class Scoring(unittest.TestCase):
    def test_words_count_by_how_few_groups_have_them_and_never_beyond_all_of_them(self):
        pool = [group("kitchen", ["cooking"], ["home kitchen with a window"]),
                group("bedroom", ["sleeping"], ["small bedroom with a window"]),
                group("library", ["reading"], ["reading room with a window"])]
        scores = retrieval.word_scores(pool, "cooking by the window")
        self.assertEqual(scores.index(max(scores)), 0)
        self.assertGreater(scores[0], scores[1], "a word every group has counts less")
        self.assertTrue(all(0 <= score <= 1 for score in retrieval.word_scores(pool, "cooking cooking kitchen")))
        self.assertEqual(retrieval.content_words("his room in the attic"), ["room", "attic"])
        self.assertEqual(retrieval.relevance(pool, "cooking"), retrieval.word_scores(pool, "cooking"),
                         "words alone without embeddings")
        self.assertEqual([round(value, 3) for value in retrieval.zscores([1, 2, 3])], [-1.225, 0.0, 1.225])

    def test_the_order_puts_unlike_groups_next_to_each_other(self):
        pool = [group("a"), group("b"), group("c")]
        vectors = [[1, 0], [.99, .14], [0, 1]]
        self.assertEqual([row["name"] for row in selection.diverse_order(pool, [3, 2.9, 2], vectors)], ["a", "c", "b"],
                         "the near copy of a waits behind a different group")
        self.assertEqual([row["name"] for row in selection.diverse_order(pool, [1, 3, 2])], ["b", "c", "a"])


class SpreadDeal(unittest.TestCase):
    def test_each_image_comes_from_the_next_group(self):
        pool = [group("bedroom", entries=["bed 1", "bed 2"]), group("kitchen", entries=["kitchen 1"]),
                group("beach", entries=["beach 1", "beach 2", "beach 3"])]
        dealt = selection.deal_spread(pool, 7, random.Random(1))
        names = {entry: row["name"] for row in pool for entry in row["entries"]}
        self.assertEqual([names[dealt[number]] for number in range(1, 8)],
                         ["bedroom", "kitchen", "beach", "bedroom", "beach", "beach", "bedroom"],
                         "the kitchen of one waits while other places are still unused")
        self.assertEqual(len({dealt[number] for number in range(1, 7)}), 6, "no place twice before all are dealt")
        self.assertEqual({dealt[1], dealt[4]}, {"bed 1", "bed 2"}, "a different entry each time a group comes back")
        self.assertEqual(len(set(selection.deal_spread(pool, 5, random.Random(1), locked=True).values())), 1)
        self.assertEqual(selection.deal_spread([], 5, random.Random(1)), {})


if __name__ == "__main__":
    unittest.main()
