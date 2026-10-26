"""Dataset Understanding (brief version 14): who, how many, what happens, what stays and what varies. Scripted model
answers only; nothing here is live-model evidence."""

import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from goated_prompter.backends.mock import MockBackend
from goated_prompter.contracts import GoatedPrompterRequest
from goated_prompter.features.dataset.v2 import understanding
from goated_prompter.features.dataset.v2.draft import default_dataset_draft
from goated_prompter.prompt_library import copied_reference

# Two answers a model gave for "magical world" (an earlier debug trace): a punctuation-only fixed and blank randomized,
# then an empty fixed, each with a stray "intent" key from the retired interpretation. Both must be usable as they are.
MAGICAL_FIRST = ('{"path": "non_character", "summary": "A magical world.", "characters": [], "fixed": ",[],", '
                 '"randomized": " ", "must": [], "avoid": [], "intent": {"elements": [], "relations": []}}')
MAGICAL_SECOND = ('{"path": "non_character", "summary": "A magical world.", "characters": [], "fixed": "", '
                  '"randomized": "setting, lighting, camera, mood, style", "must": [], "avoid": []}')
TWO_MEN = json.dumps({"path": "character", "summary": "Two men in an explicit scene", "fixed": "Two adult men",
                      "randomized": "Position, place, lighting", "must": [], "avoid": [],
                      "characters": [{"label": "man", "gender": "male", "custom": "", "pronoun": "he", "count": 2}]})


class Understanding(unittest.TestCase):
    def understand(self, answers, **data):
        backend = MockBackend()
        replies = iter(answers)
        calls = []

        def generate(instruction):
            calls.append(instruction)
            return next(replies)
        values = {**default_dataset_draft(), "subject": "magical world", "amount": 3, "seed": 5, "seed_mode": "fixed", **data}
        with patch.object(backend, "generate", side_effect=generate), \
                patch.object(understanding, "create_backend", return_value=backend), \
                patch.object(understanding, "resolve_director_config", return_value=({}, None)):
            result = understanding.understand({"backend": "mock"}, SimpleNamespace(selected_prompt_model="Default"), values,
                                              progress=lambda _: None)
        return result, calls

    def test_two_men_in_an_explicit_scene_keeps_two_men_and_the_activity(self):
        result, calls = self.understand([TWO_MEN], subject="2 adult men in an explicit scene", nsfw=True)
        self.assertEqual(len(calls), 1)
        self.assertEqual((result["path"], result["people"]), ("nsfw_character", 2))
        self.assertEqual([(person["label"], person["gender"], person["pronoun"]) for person in result["characters"]],
                         [("man 1", "male", "he"), ("man 2", "male", "he")])
        self.assertIn("explicit scene", result["summary"])
        self.assertEqual(result["input"]["request"], "2 adult men in an explicit scene", "the request itself is kept word for word")

    def test_each_character_keeps_the_requests_own_words_about_how_it_looks(self):
        # Live sets lost a requested beard, tattoos and age: they had no owner past the subject's words.
        answer = json.loads(TWO_MEN)
        answer["characters"] = [{"label": "man", "gender": "male", "custom": "", "pronoun": "he", "count": 2,
                                 "appearance": "short beard, a scar on the cheek and sleeve tattoos"},
                                {"label": "woman", "gender": "female", "custom": "", "pronoun": "she", "count": 1}]
        result, _ = self.understand([json.dumps(answer)], subject="two men with sleeve tattoos and a short beard, a woman")
        self.assertEqual([(person["label"], person["appearance"]) for person in result["characters"]],
                         [("man 1", "short beard, sleeve tattoos"), ("man 2", "short beard, sleeve tattoos"),
                          ("woman", "")], "only words the user wrote, for every person of the entry")
        self.assertIn("appearance", understanding.instruction({"subject": "x"}).json_schema["properties"]["characters"]
                      ["items"]["properties"])

    def test_the_path_follows_who_appears_and_the_model_never_judges_it(self):
        # A model that first judged whether "characters are the point" listed no one for a man reading in a cafe, a
        # chef, a cat or a robot; a cast and a path could also disagree.
        man = {"label": "man", "gender": "male", "custom": "", "pronoun": "he", "count": 1}
        answer = {**json.loads(MAGICAL_FIRST), "path": "non_character", "characters": [man]}
        result, calls = self.understand([json.dumps(answer)], subject="a man reading a book in a cafe")
        self.assertEqual((result["path"], [person["label"] for person in result["characters"]], len(calls)),
                         ("sfw_character", ["man"], 1), "the cast decides, a stray path is ignored")
        self.assertNotIn("path", calls[0].json_schema["properties"])
        self.assertIn("even when the request is mostly about what they do, what they hold or where they are",
                      " ".join(calls[0].system_message.split()))
        result, _ = self.understand([json.dumps({**answer, "characters": []})], subject="a perfume bottle on a table")
        self.assertEqual(result["path"], "non_character", "no one appears")
        result, _ = self.understand([json.dumps({**answer, "characters": [man]})], subject="a man in a cafe", nsfw=True)
        self.assertEqual(result["path"], "nsfw_character")

    def test_understanding_never_chooses_vocabulary(self):
        result, calls = self.understand([TWO_MEN], subject="2 adult men in an explicit scene", nsfw=True)
        self.assertEqual(result["version"], 17)
        self.assertNotIn("intent", result)
        self.assertEqual(set(calls[0].json_schema["properties"]), set(understanding.MODEL_FIELDS))
        for word in ("pack", "vocabulary"):
            self.assertNotIn(word, calls[0].user_message.casefold())

    def test_broad_request_with_malformed_optional_text_is_understood_in_one_call(self):
        result, calls = self.understand([MAGICAL_FIRST])
        self.assertEqual(len(calls), 1, "a recoverable answer is not regenerated")
        self.assertEqual((result["path"], result["fixed"], result["randomized"]), ("non_character", "", ""))
        self.assertEqual(result["summary"], "A magical world.")
        self.assertNotIn("intent", result, "a stray intent is not kept")
        self.assertEqual(understanding.validate_brief(result), result)

    def test_the_second_magical_world_answer_is_also_valid(self):
        result, calls = self.understand([MAGICAL_SECOND])
        self.assertEqual(len(calls), 1)
        self.assertEqual((result["fixed"], result["randomized"]), ("", "setting, lighting, camera, mood, style"))

    def test_missing_summary_falls_back_to_the_request_never_to_an_invention(self):
        answer = json.loads(MAGICAL_SECOND)
        answer["summary"] = "  "
        result, _ = self.understand([json.dumps(answer)])
        self.assertEqual(result["summary"], "magical world")

    def test_nsfw_switch_keeps_a_place_request_without_people(self):
        result, calls = self.understand([MAGICAL_FIRST], nsfw=True)
        self.assertEqual(len(calls), 1)
        self.assertEqual((result["path"], result["people"], result["input"]["nsfw"]), ("non_character", 0, True))
        self.assertIn("without people", calls[0].system_message)

    def test_nsfw_adult_request_without_people_is_still_sent_back(self):
        errors = understanding.model_errors(understanding.recover(json.loads(MAGICAL_FIRST)), True,
                                            {"subject": "two people in an explicit scene", "source_mode": "random"})
        self.assertTrue(any("list them in characters" in error for error in errors), errors)

    def test_unrecoverable_answers_still_fail_after_one_retry(self):
        broken = json.dumps({**json.loads(MAGICAL_FIRST), "characters": "nobody"})
        with self.assertRaisesRegex(ValueError, "invalid answer twice"):
            self.understand([broken, broken])

    def test_a_saved_version_10_brief_with_intent_stays_readable(self):
        result, _ = self.understand([MAGICAL_SECOND])
        saved = {**{key: value for key, value in result.items() if key not in ("kept", "consistency", "kept_words", "places")},
                 "version": 10, "intent": {"elements": [], "relations": []}}
        self.assertEqual(understanding.validate_brief(saved), saved)

    def test_the_places_give_the_setting_the_world_and_ideas_for_a_request_without_a_place(self):
        # A request with a room in a larger surrounding lost the surrounding when one place had to win.
        named = {**json.loads(MAGICAL_SECOND), "kept": {"place": "in his room in space"},
                 "places": {"setting": "in space", "world": "sci-fi", "ideas": ["a hangar"]}}
        result, _ = self.understand([json.dumps(named)], subject="a reader asleep in his room in space")
        self.assertEqual(result["places"], {"setting": "in space", "world": "sci-fi", "ideas": ["a hangar"]},
                         "ideas are kept for a named place too: they are its fallback")
        # Live briefs kept a time of day and an act as the place and filed acts as clothing or expression, so no place
        # was dealt; and called a story character's ordinary surroundings another world.
        prompt = " ".join(understanding.SYSTEM.split())
        for rule in ("place: where the images happen, or what someone is on or in; never a time of day, the weather or "
                     "an act", "light: the lighting and the time of day", "clothing: what anyone wears: garments and "
                     "accessories only", "every act and what it leaves on the body stays here",
                     "the world of the surroundings the images happen in", "always 6 to 8 different places",
                     "When kept names a place, every idea is that place or a kind of it, never another place"):
            self.assertIn(rule, prompt)
        # A live brief gave the whole place as its setting: that is no setting.
        same = {**named, "kept": {"place": "in his room"}, "places": {**named["places"], "setting": "in his room"}}
        result, _ = self.understand([json.dumps(same)], subject="a reader asleep in his room")
        self.assertEqual(result["places"]["setting"], "")
        loose = {**json.loads(MAGICAL_SECOND), "places": {"setting": "on the moon", "world": "everyday",
                                                          "ideas": ["a city street", " ", "a kitchen"]}}
        result, _ = self.understand([json.dumps(loose)], subject="a reader telling jokes")
        self.assertEqual(result["places"], {"setting": "", "world": "everyday", "ideas": ["a city street", "a kitchen"]},
                         "a setting the user never wrote is dropped")
        result, _ = self.understand([MAGICAL_SECOND], subject="a reader telling jokes")
        self.assertEqual(result["places"], {"setting": "", "world": "everyday", "ideas": []}, "places is optional")
        self.assertIn("6 to 8 different places", " ".join(understanding.SYSTEM.split()))
        # A live request without a place got six homely ideas and lost every public, event and performance place.
        self.assertIn("the obvious ones and less expected ones that still fit",
                      " ".join(understanding.SYSTEM.split()))
        with self.assertRaises(ValueError):
            understanding.validate_brief({**result, "places": {**result["places"], "world": "the moon"}})

    def test_words_of_who_appears_and_what_happens_are_never_kept_as_another_part(self):
        # Live briefs kept the act as clothing in most requests (clothing was filled right after the subject), and one
        # copied the act into every part.
        answer = {**json.loads(MAGICAL_SECOND), "kept": {
            "subject": "a reader", "action": "reading a book quietly", "clothing": "reading a book",
            "expression": "quietly", "objects": "a book", "mood": "reading a book quietly"}}
        result, _ = self.understand([json.dumps(answer)], subject="a reader reading a book quietly")
        self.assertEqual(result["kept_words"], {"subject": "a reader", "action": "reading a book quietly",
                                                "objects": "a book"}, "a piece of the act may still be an object")
        dressed = {**json.loads(MAGICAL_SECOND), "kept": {"subject": "a reader", "clothing": "in a red coat",
                                                         "action": "reading"}}
        result, _ = self.understand([json.dumps(dressed)], subject="a reader in a red coat reading")
        self.assertEqual(result["kept_words"]["clothing"], "in a red coat")
        schema = understanding._schema()["properties"]["kept"]["properties"]
        self.assertLess(list(schema).index("action"), list(schema).index("clothing"), "the act is filled first")

    def test_the_parts_the_request_mentions_are_kept_and_the_rest_vary(self):
        # A request that named one place and one pose had every scene asked again as a repeat of the first.
        # A part counts only when the words quoted for it are the user's own; the model also listed parts nobody named.
        answer = {**json.loads(MAGICAL_SECOND), "kept": {"action": "Reading", "place": "in one  armchair",
                                                         "light": "warm lamplight", "weather": "rain", "mood": ""}}
        result, _ = self.understand([json.dumps(answer)], subject="a reader reading in one armchair in a library")
        self.assertEqual(result["kept_words"], {"action": "Reading", "place": "in one armchair"},
                         "the user's words only, case and spacing aside")
        # A Character dataset keeps its people's looks by default; a mentioned part is at least themed.
        self.assertEqual(result["kept"], ["subject", "action", "place"])
        self.assertEqual({part: level for part, level in result["consistency"].items() if level != "free"},
                         {"subject": "themed", "action": "themed", "place": "themed"})
        self.assertIn("every part not mentioned is chosen anew for each image", " ".join(understanding.SYSTEM.split()))
        # Live briefs listed in randomized the parts kept quotes, and repeated the request in fixed and must, so the
        # scene writer got the same request three times and two answers about what varies.
        for rule in ("only what the user explicitly asks to vary", "never list a part that kept quotes",
                     "never repeat summary", '"" when summary already says them all'):
            self.assertIn(rule, " ".join(understanding.SYSTEM.split()))
        self.assertTrue(all(f"\n  {part}: " in understanding.SYSTEM for part in understanding.KEPT_PARTS),
                        "every part is defined for the model")
        # A live request asked for the feet; read as a requirement but not as framing, it got hips-up frames dealt.
        self.assertIn("camera: the viewpoint, the framing, the kind of shot, or which body parts the image must show",
                      understanding.SYSTEM)
        result, _ = self.understand([MAGICAL_SECOND])
        self.assertEqual((result["kept"], result["kept_words"]), (["subject"], {}), "only the type's default")

    def test_the_request_and_the_draft_set_each_parts_level(self):
        # A pose dataset drifted because every image was told to vary how the act happens; a background the request
        # asked to keep was moved to another spot in every image.
        answer = {**json.loads(MAGICAL_SECOND), "kept": {"action": "Reading", "place": "in the same armchair",
                                                         "light": "warm lamplight"},
                  "locked": ["place", "camera", "action"], "varied": ["light"]}
        subject = "a reader reading in the same armchair in a library, warm lamplight in various colours"
        result, _ = self.understand([json.dumps(answer)], subject=subject)
        levels = result["consistency"]
        # A live model also locked parts the request only named; a lock needs the user's own words to ask for it.
        self.assertEqual((levels["place"], levels["camera"], levels["light"], levels["action"]),
                         ("locked", "free", "free", "themed"), "locked and varied count only for mentioned parts")
        result, _ = self.understand([json.dumps(answer)], subject=subject, trigger_type="Pose / action",
                                    consistency={"light": "locked", "mood": "themed"})
        levels = result["consistency"]
        self.assertEqual((levels["action"], levels["light"], levels["mood"], levels["subject"]),
                         ("locked", "locked", "themed", "free"), "the type's default, then the draft's own choice")
        self.assertIn("locked: only the parts in kept the request says must look identical in every image",
                      " ".join(understanding.SYSTEM.split()))
        self.assertIn("varied: the parts in kept the request asks to differ between the images", understanding.SYSTEM)
        with self.assertRaisesRegex(ValueError, "consistency must give every part"):
            understanding.validate_brief({**result, "consistency": {"place": "locked"}})
        from goated_prompter.features.dataset.v2 import consistency
        old = {key: value for key, value in result.items() if key not in ("consistency", "kept_words")}
        self.assertEqual(consistency.levels({**old, "kept": ["place"]})["place"], "themed", "a version 14 brief")
        self.assertEqual(consistency.levels({**old, "kept": ["place"]})["action"], "free")
        self.assertEqual(understanding.validate_brief(result), result)
        with self.assertRaises(ValueError):
            understanding.validate_brief({**result, "kept": ["weather"]})


class LibraryReferences(unittest.TestCase):
    """The Prompt Library may guide wording, never add a template's content to a Dataset prompt."""
    TEMPLATE = "Soft window light falls across the quiet room while dust drifts slowly through the warm afternoon air."

    def test_copy_check_names_the_copied_passage(self):
        copied = copied_reference("A man reads. Soft window light falls across the quiet room while dust drifts slowly.",
                                  [self.TEMPLATE])
        self.assertEqual(copied, "soft window light falls across the quiet room while dust")

    def test_wording_the_request_itself_contains_is_not_a_copy(self):
        idea = "the quiet room while dust drifts slowly through the warm afternoon air"
        prompt = "A man reads in " + idea + "."
        self.assertTrue(copied_reference(prompt, [self.TEMPLATE]))
        self.assertEqual(copied_reference(prompt, [self.TEMPLATE], allowed=[idea]), "")

    def test_retry_after_copying_is_written_without_the_templates(self):
        from goated_prompter.features.builder import service as builder
        backend = MockBackend()
        instructions = []

        def generate(instruction):
            instructions.append(instruction)
            return self.TEMPLATE if len(instructions) == 1 else "A reader sits by a bright window with a book."
        request = GoatedPrompterRequest(idea="a reader by a window", planning_mode="Direct", target_model="Krea 2")
        with patch.object(backend, "generate", side_effect=generate), \
                patch.object(builder, "create_backend", return_value=backend), \
                patch.object(builder, "pick_references", return_value=(self.TEMPLATE,)):
            result = builder.GoatedPrompterService({"backend": "mock"}).generate_text_only(request)
        self.assertEqual(result.prompt, "A reader sits by a bright window with a book.")
        self.assertEqual(len(instructions), 2)
        self.assertIn("TEMPLATES FROM THE USER'S PROMPT LIBRARY", instructions[0].system_message)
        self.assertNotIn(self.TEMPLATE, instructions[1].system_message)
        self.assertIn("copied wording", instructions[1].system_message)


if __name__ == "__main__":
    unittest.main()
