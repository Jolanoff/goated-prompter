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


def poses(*rows):
    """One group of entries with their people counts: (entry, people or None)."""
    return [{"name": "poses", "words": [], "entries": [entry for entry, _ in rows], "worlds": None, "adult": False,
             "selected": True, "people": {entry: count for entry, count in rows if count}}]


class Constraints(unittest.TestCase):
    def test_entries_are_made_for_the_casts_number_of_people(self):
        rows = poses(("A reading", 1), ("A and B dancing", 2), ("A group seated around a meal", 3), ("A waving", None))
        entries = lambda size: [entry for group in retrieval.for_cast(rows, size) for entry in group["entries"]]
        self.assertEqual(entries(1), ["A reading", "A waving"], "an entry without a count fits every cast")
        self.assertEqual(entries(2), ["A and B dancing", "A waving"], "a pair never gets a pose for one person alone")
        self.assertEqual(entries(5), ["A group seated around a meal", "A waving"], "an entry for a group serves a larger one")
        self.assertEqual(entries(2), entries(2))
        only_solo = poses(("A reading", 1), ("A stretching", 1))
        self.assertEqual(retrieval.for_cast(only_solo, 2), only_solo, "no entry for the cast: the most people below it")

    def test_an_entry_saying_what_the_request_rules_out_is_never_kept(self):
        rows = poses(("A kneeling by a fire", 1), ("A kneels to tie a shoe", 1), ("A standing at a window", 1))
        kept = retrieval.without_said(rows, ["no kneeling", ""])
        self.assertEqual(kept[0]["entries"], ["A standing at a window"], "any form of the word")
        self.assertEqual(retrieval.without_said(rows, []), rows)

    def test_entries_that_say_an_action_are_found_in_a_pack_of_plain_entries(self):
        rows = poses(("A and B dancing close", 2), ("A and B dancing apart", 2), ("A and B reading", 2))
        found = retrieval.match(rows, "a slow dance", entry_words=True)
        self.assertEqual(found[0]["entries"], ["A and B dancing close", "A and B dancing apart"],
                         "dance: dancing, though most of the pack says it")
        self.assertEqual(retrieval.match(rows, "a slow dance"), [], "without entry words a plain pack has no group words")
        self.assertEqual(retrieval.match(rows, "juggling", entry_words=True), [], "an act no entry shows finds none")

    def test_a_group_word_said_in_another_form_finds_its_group_after_the_entries(self):
        # A request's own act ("reads") came back as no entry: its group says "reading" and its entries never do.
        rows = [{"name": "reading", "words": ["reading", "book"], "entries": ["A seated with a novel open on the lap"],
                 "worlds": None, "adult": False, "selected": True},
                {"name": "giving", "words": ["handing over"], "entries": ["A holding a cup out to B"],
                 "worlds": None, "adult": False, "selected": True},
                {"name": "greetings", "words": ["greeting"], "entries": ["A and B clasping each other's hand"],
                 "worlds": None, "adult": False, "selected": True}]
        self.assertEqual([row["name"] for row in retrieval.match(rows, "reads", entry_words=True)], ["reading"])
        self.assertEqual([row["name"] for row in retrieval.match(rows, "shaking hands", entry_words=True)],
                         ["greetings"], "an entry that says the words comes first")

    def test_a_group_word_of_several_words_is_said_in_any_order_with_words_between(self):
        # An act that put a word between the words of its group's trigger never said it, so another group's single
        # word won.
        rows = [{"name": "sword drills", "words": ["sword", "drawing a sword"], "entries": ["A drawing a blade"],
                 "worlds": None, "adult": False, "selected": True},
                {"name": "sketching", "words": ["drawing", "sketching"], "entries": ["A with a sketchbook"],
                 "worlds": None, "adult": False, "selected": True},
                {"name": "grooming", "words": ["brushing hair"], "entries": ["A brushing B's hair"],
                 "worlds": None, "adult": False, "selected": True}]
        names = lambda text: [row["name"] for row in retrieval.match(rows, text, entry_words=True)]
        self.assertEqual(names("drawing his sword"), ["sword drills"], "the group whose word covers more of the act")
        self.assertEqual(names("brushing her friend's hair"), ["grooming"])
        self.assertEqual(names("hair brushing"), ["grooming"], "any order")
        self.assertEqual(names("drawing"), ["sketching"])
        self.assertEqual([row["name"] for row in retrieval.match(rows, "brushing her friend's hair")], [],
                         "without entry words a group word is still said whole and in order")


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

    def test_an_entry_is_made_of_parts_named_by_what_they_describe(self):
        self.assertEqual(retrieval.entry_parts("long salt-and-pepper hair with grey-green eyes and fair skin"),
                         [("hair", "long salt-and-pepper hair"), ("ey", "grey-green eyes"), ("skin", "fair skin")])
        self.assertEqual([facet for facet, _ in retrieval.entry_parts("bald head and a short beard with grey eyes")],
                         ["head", "beard", "ey"])

    def test_a_request_fixes_only_the_parts_it_names(self):
        looks = [group("female", ["woman"], ["copper red hair with blue eyes and freckled fair skin",
                                             "long wavy black hair with grey eyes and dark umber skin",
                                             "sleek brown hair with dark brown eyes and pale skin",
                                             "short red hair with wide pale blue eyes and tan skin"])]
        asked = lambda text: retrieval.requested_parts(looks, text)
        self.assertEqual(asked("a woman with red hair and blue eyes"),
                         ({"hair": ["copper red hair", "short red hair"], "ey": ["blue eyes", "wide pale blue eyes"]}, []),
                         "a live ginger man with green eyes kept one whole look, hairstyle and skin, in every image")
        self.assertEqual(asked("a freckled redhead")[0], {"skin": ["freckled fair skin"],
                                                          "hair": ["copper red hair", "short red hair"]},
                         "word forms and a word that starts with a part's word")
        self.assertEqual(asked("a blue-eyed woman with dark skin")[0],
                         {"ey": ["blue eyes", "wide pale blue eyes"], "skin": ["dark umber skin"]},
                         "dark brown eyes are not dark skin")
        self.assertEqual(asked("a pale woman")[0], {"skin": ["pale skin"]}, "pale sits nearest skin's own word")
        self.assertEqual(asked("a woman with long hair")[0], {"hair": ["long wavy black hair"]})
        self.assertEqual(asked("a tall woman in a brown dress"), ({}, ["tall", "brown dress"]),
                         "what no part says is returned in the text's own words")
        self.assertEqual(asked("a 22 year old woman with red hair and black hair and a nose ring"),
                         ({"hair": ["copper red hair", "short red hair"]}, ["22 year old", "nose ring", "black hair"]),
                         "a detail that contradicts one before it in the same part")
        self.assertEqual(retrieval.requested_parts([], "a woman with red hair"), ({}, ["woman", "red hair"]),
                         "without entries every detail is the text's own")
        self.assertEqual((retrieval.word_stem("freckles"), retrieval.word_stem("freckled"), retrieval.word_stem("red"),
                          retrieval.word_stem("blond"), retrieval.word_stem("blonde")),
                         ("freckl", "freckl", "red", "blond", "blond"))

    def test_a_part_no_entry_has_beside_the_fixed_ones_stays_the_texts_own(self):
        looks = [group("male", ["man"], ["ginger hair with green eyes and fair skin", "black hair with brown eyes and tan skin",
                                         "bald head and a short boxed beard with grey eyes and pale skin"])]
        self.assertEqual(retrieval.requested_parts(looks, "a ginger man with a short beard"),
                         ({"hair": ["ginger hair"]}, ["short beard"]), "no look has hair and a beard")
        self.assertEqual(retrieval.requested_parts(looks, "a bald man with a short beard")[0],
                         {"head": ["bald head"], "beard": ["a short boxed beard"]})

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

    def test_with_entry_words_meaning_alone_finds_nothing(self):
        # An act is not shown by an entry that is only near it in meaning: a live set dealt unrelated pair tasks to a
        # request whose act no entry said, because their group stood out by meaning.
        pool = [group(name) for name in ("bedroom", "kitchen", "beach", "garage", "garden", "office")]
        vectors = {retrieval.group_text(row): [float(number == index) for number in range(6)]
                   for index, row in enumerate(pool)}
        embeddings = self.embeddings(Embedder({**vectors, "a sleeping chamber": [.95, .05, 0, 0, 0, 0]}))
        self.assertEqual([row["name"] for row in retrieval.match(pool, "a sleeping chamber", embeddings)], ["bedroom"],
                         "a group that stands out by meaning is found")
        self.assertEqual(retrieval.match(pool, "a sleeping chamber", embeddings, entry_words=True), [],
                         "with entry words, words decide")

    def six(self, *rows, text, near):
        """Six groups (rows first, then filler), one-hot meanings, and the text's meaning at the group named near."""
        names = [row["name"] for row in rows]
        pool = [*rows, *(group(name, entries=[f"A at the {name}"]) for name in
                         ("kitchen", "beach", "garage", "garden", "office", "harbor") if name not in names)][:6]
        vectors = {retrieval.group_text(row): [float(number == index) for number in range(6)]
                   for index, row in enumerate(pool)}
        vectors[text] = [.95 if row["name"] == near else .05 for row in pool]
        return pool, self.embeddings(Embedder(vectors))

    def test_with_entry_words_a_group_found_alone_stays_whatever_the_other_words_mean(self):
        # A live act lost its group because its other words lowered the group's meaning score against the other
        # offered groups, and the same act kept it when fewer packs were selected.
        rows = (group("stretching", entries=["A bending forward"]), group("office", entries=["A on a mat by a desk"]))
        pool, embeddings = self.six(*rows, text="stretching on a mat", near="office")
        self.assertEqual([row["name"] for row in retrieval.match(pool, "stretching on a mat", embeddings,
                                                                 entry_words=True)], ["stretching"])
        self.assertEqual([row["name"] for row in retrieval.match(pool, "stretching on a mat", embeddings)], ["office"],
                         "without entry words meaning still judges a partial word match")

    def test_with_entry_words_meaning_settles_groups_that_compete_for_different_words(self):
        rows = (group("fixing", entries=["A at a workbench"]), group("bike", entries=["A riding along a path"]))
        pool, embeddings = self.six(*rows, text="fixing his old bike", near="fixing")
        self.assertEqual([row["name"] for row in retrieval.match(pool, "fixing his old bike", embeddings,
                                                                 entry_words=True)], ["fixing"])
        both = [group("fixing", entries=["A at a workbench"]), group("bike", entries=["A riding along a path"])]
        self.assertEqual([row["name"] for row in retrieval.match(both, "fixing his bike", entry_words=True)],
                         ["fixing", "bike"], "groups that explain every word between them all stay")

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

    def test_cached_vectors_are_compact_and_the_cache_has_no_user_store_size_limit(self):
        # A large vocabulary passed the 16 MiB user-store limit and the run failed while saving the cache; decoded
        # vectors kept as Python float lists took ten times the memory of the cached 32-bit floats.
        from array import array
        from unittest.mock import patch
        from goated_prompter.json_store import atomic_json
        texts = [retrieval.group_text(row) for row in self.pool]
        with patch.object(vectors_module, "atomic_json") as save:
            self.embeddings().documents(texts)
        self.assertIs(save.call_args.kwargs["bounded"], False, "the cache is saved without the user-store limit")
        vectors = self.embeddings().documents(texts)
        self.assertTrue(all(isinstance(vector, array) and vector.typecode == "f" for vector in vectors))
        self.assertEqual(self.embeddings().documents(texts), vectors, "a later run reads the same values back")
        with self.assertRaisesRegex(ValueError, "16 MiB"):
            atomic_json(self.folder / "store.json", {"records": "x" * (16 * 1024 * 1024)})
        self.assertFalse((self.folder / "store.json").exists(), "user stores keep their limit")

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

    def test_an_embedding_server_has_an_exit_hook_only_while_it_runs(self):
        # Every run's embedder registered an exit hook for good, so a long-running app kept one per run.
        from unittest.mock import MagicMock, patch
        from goated_prompter.backends import llama_cpp_process as llama
        config = MagicMock(host="127.0.0.1", startup_timeout=5, executable=self.folder / "server.exe")
        config.command.return_value = ["server"]
        process = MagicMock(pid=7)
        process.poll.return_value = None
        with patch.object(llama, "atexit") as hooks, patch.object(llama, "_spawn", return_value=process), \
                patch.object(llama, "_await_health", return_value="ready"), patch.object(llama, "_stop") as stop:
            embedder = llama.LlamaCppEmbedder(config)
            hooks.register.assert_not_called()
            embedder._start()
            hooks.register.assert_called_once_with(embedder.close)
            embedder.close()
            hooks.unregister.assert_called_with(embedder.close)
            stop.assert_called_once_with(process)
            with patch.object(llama, "_await_health", return_value=3):
                with self.assertRaisesRegex(BackendGenerationError, "exited during startup with code 3"):
                    embedder._start()
            self.assertIsNone(embedder._process, "a server that failed to start is let go, its hook with it")

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


class Narrowing(unittest.TestCase):
    def test_a_detail_the_group_words_do_not_explain_picks_its_entries(self):
        # A white background got every coloured backdrop, a rainy street every street.
        folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, folder, True)
        streets = group("street", ["city street"], [f"street {name} with shops" for name in
                                                    ("rainy", "sunny", "busy", "quiet", "old", "wide", "narrow")])
        vectors = {entry: [1, 0] if "rainy" in entry else [0, 1] for entry in streets["entries"]}
        vectors["a rainy street"] = [1, 0]
        embeddings = vectors_module.Embeddings(Embedder(vectors), folder / "cache.json", progress=lambda _: None)
        self.assertEqual(retrieval.narrowed([streets], "a rainy street", embeddings)[0]["entries"], ["street rainy with shops"])
        self.assertEqual(retrieval.narrowed([streets], "a city street", embeddings), [streets],
                         "words the group's own words explain point to every entry")
        self.assertEqual(retrieval.narrowed([streets], "a rainy street"), [streets], "without embeddings: by name only")


class Related(unittest.TestCase):
    def test_only_groups_close_to_an_anchor_are_related(self):
        folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, folder, True)
        names = ["restroom", "bathroom", "bedroom", "kitchen", "beach", "office", "park", "garage"]
        pool = [group(name, entries=[f"{name} place"]) for name in names]
        direction = {"restroom": [1, 0, 0], "bathroom": [.95, .3, 0], "bedroom": [0, 1, 0], "kitchen": [0, .9, .4],
                     "beach": [0, 0, 1], "office": [0, .6, .8], "park": [0, .2, 1], "garage": [0, .7, .7]}
        vectors = {text: direction[row["name"]] for row in pool for text in (retrieval.group_text(row), *row["entries"])}
        embeddings = vectors_module.Embeddings(Embedder(vectors), folder / "cache.json", progress=lambda _: None)
        found = retrieval.related(pool, pool[:1], pool, embeddings)
        self.assertEqual([row["name"] for row in found], ["restroom", "bathroom"])
        self.assertEqual(retrieval.related(pool, pool[:1], pool, None), pool[:1], "without embeddings: the anchors only")


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

    def test_composed_entries_keep_the_fixed_parts_and_vary_the_rest(self):
        pool = [group("male", entries=["black hair with brown eyes and tan skin", "blond hair with grey eyes and pale skin",
                                       "brown hair with blue eyes and olive skin",
                                       "bald head and a beard with hazel eyes and dark skin"])]
        fixed = {"hair": ["ginger hair", "short ginger hair"], "ey": ["green eyes"]}
        dealt = selection.deal_composed(pool, fixed, 3, random.Random(2))
        self.assertTrue(all(look.startswith(("ginger hair with green eyes", "short ginger hair with green eyes"))
                            for look in dealt.values()), dealt)
        self.assertEqual({look.rsplit(" and ", 1)[1] for look in dealt.values()}, {"tan skin", "pale skin", "olive skin"},
                         "every part the request leaves free varies, from entries that have the fixed parts")
        self.assertEqual(len(set(selection.deal_composed(pool, {}, 4, random.Random(2)).values())), 4)


if __name__ == "__main__":
    unittest.main()
