"""Adult switch registry, cast/anatomy eligibility, vocabulary selection and selected scene facts."""

from collections import Counter
from dataclasses import replace
import json
import random
import unittest
from unittest.mock import Mock, patch

from goated_prompter.backends.base import BackendGenerationError
from goated_prompter.contracts import GoatedPrompterRequest
from goated_prompter.features.dataset.assignments import dataset_assignments
from goated_prompter.features.dataset.batch_planner import (freeze_scene_spec, pick_position, plan_scene_specs, position_tiers,
                                                            propose_scene_specs, scene_fact_choices)
from goated_prompter.features.dataset.compatibility import compatible_arrangements, compatible_entry
from goated_prompter.features.dataset.modules import MODULES, MODULES_BY_NAME, Module, resolve_switches
from goated_prompter.features.dataset.private_vocabulary import SECTIONS, parse_vocabulary
from goated_prompter.features.dataset.prompting import dataset_instruction
from goated_prompter.features.dataset.quality import scene_fact_error
from goated_prompter.features.dataset.routing import resolve_route, routing_clarifications
from goated_prompter.features.dataset.scene_spec import Contact, SceneSpec
from goated_prompter.features.dataset.service import DatasetService
from goated_prompter.features.dataset.understanding import validate_modules
from tests.helpers import dataset_understanding_fixture
from tests.support.dataset import checked_scene, checked_writer_responses, planned_facts, planned_scene, valid_draft


def adult_draft(*sexes, subject="Adults having sex", traits=None, modules=None, **changes):
    characters = [{"name": f"adult {index}", "count": 1, "sex": sex, "kind": "human", "origin": "described",
                   "series": "", "traits": (traits or {}).get(index, "")} for index, sex in enumerate(sexes, 1)]
    brief = dataset_understanding_fixture(character_count=len(sexes), characters=characters,
                                          **({"modules": modules} if modules else {}))
    return valid_draft(**{"subject": subject, "trigger": "", "amount": 4, "trigger_type": "Multiple characters",
                          "_confirmed_intent": brief, **changes})


def eligible(*sexes, **options):
    route = resolve_route(adult_draft(*sexes, **options))
    return set(scene_fact_choices(route, None, ((), (), ())).get("eligible_activities", "").split(", ")) - {""}


class RegistryTests(unittest.TestCase):
    def test_every_module_is_defined_once_with_known_sections_and_acyclic_implications(self):
        names = [module.name for module in MODULES]
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual({module.name for module in MODULES if module.kind == "core"}, {"anal", "oral", "vaginal"})
        for module in MODULES:
            self.assertIn(module.kind, {"core", "optional", "event"})
            for section in (*module.sections, *module.solo_sections, *(section for _, section in module.styling)):
                self.assertIn(section, SECTIONS, section)
            seen, pending = set(), list(module.implies)
            while pending:
                name = pending.pop()
                self.assertIn(name, MODULES_BY_NAME)
                self.assertNotEqual(name, module.name, "implications must not cycle")
                if name not in seen:
                    seen.add(name)
                    pending.extend(MODULES_BY_NAME[name].implies)
        self.assertNotIn("aftercare", MODULES_BY_NAME)

    def test_optional_modules_default_off_and_finish_and_solo_toys_are_eligible(self):
        self.assertEqual(resolve_switches((), (), 2), {"finish"})
        self.assertEqual(resolve_switches((), (), 1), {"finish", "toys"})
        self.assertEqual(resolve_switches((), ("toys",), 1), {"finish"})

    def test_implications_never_override_exclusions_or_enable_unrelated_modules(self):
        implied = Module("pet", "optional", MODULES_BY_NAME["pet"].pattern, implies=("kink",))
        with patch.dict(MODULES_BY_NAME, {"pet": implied}):
            self.assertEqual(resolve_switches({"pet"}, (), 2), {"pet", "kink", "finish"})
            self.assertEqual(resolve_switches({"pet"}, {"kink"}, 2), {"pet", "finish"})


class CastEligibilityTests(unittest.TestCase):
    def test_core_activities_follow_cast_and_anatomy(self):
        cases = {("male", "male"): {"anal", "oral"}, ("male",) * 3: {"anal", "oral"},
                 ("female", "female"): {"anal", "oral", "vaginal"}, ("female",) * 3: {"anal", "oral", "vaginal"},
                 ("male", "female"): {"anal", "oral", "vaginal"}, ("male", "male", "female"): {"anal", "oral", "vaginal"},
                 ("male", "female", "female"): {"anal", "oral", "vaginal"}, ("male",) * 5: {"anal", "oral"}}
        for sexes, expected in cases.items():
            with self.subTest(sexes=sexes):
                self.assertEqual(eligible(*sexes), expected)

    def test_supplied_anatomy_is_respected_per_participant(self):
        self.assertEqual(eligible("male", "male", traits={2: "has a vagina"}), {"anal", "oral", "vaginal"})
        self.assertEqual(eligible("female", "female", traits={1: "no vagina", 2: "no vagina"}), {"anal", "oral"})

    def test_exclusions_and_only_wording_narrow_the_eligible_activities(self):
        self.assertEqual(eligible("male", "female", subject="Adults having sex, no oral"), {"anal", "vaginal"})
        self.assertEqual(eligible("male", "female", subject="Adults having only anal sex"), {"anal"})
        route = resolve_route(adult_draft("male", "female", subject="Adults having anal sex"))
        self.assertEqual(route.required, {"anal"})

    def test_female_casts_use_manual_methods_without_toys_and_never_invent_a_penis(self):
        route = resolve_route(adult_draft("female", "female"))
        self.assertTrue(compatible_entry("one woman fingers the other, vaginal contact", route, category="vaginal", position=True))
        self.assertFalse(compatible_entry("vaginal sex with a strap-on", route, category="vaginal", position=True))
        self.assertFalse(compatible_entry("she rides his penis", route, position=True))
        toys = resolve_route(adult_draft("female", "female", subject="Adults having sex with toys"))
        self.assertTrue(compatible_entry("vaginal sex with a strap-on", toys, category="vaginal", position=True))

    def test_male_casts_need_stated_vaginal_anatomy(self):
        self.assertFalse(compatible_entry("vaginal penetration", resolve_route(adult_draft("male", "male", "male")),
                                          category="vaginal", position=True))
        self.assertTrue(compatible_entry("vaginal penetration", resolve_route(adult_draft(
            "male", "male", traits={2: "has a vagina"})), category="vaginal", position=True))


class ActivationTests(unittest.TestCase):
    def asked(self, subject, *sexes):
        return set(resolve_route(adult_draft(*(sexes or ("male", "female")), subject=subject)).asked)

    def test_each_switch_turns_on_only_when_requested(self):
        cases = {"kink": "rough BDSM sex", "toys": "sex with a vibrator", "feet": "sex with foot worship",
                 "pet": "sex with human pet roleplay", "furniture": "sex using one partner as a human table",
                 "props": "sex with props", "finish": "sex at climax"}
        for name, subject in cases.items():
            with self.subTest(name=name):
                self.assertIn(name, self.asked(subject))
                self.assertNotIn(name, self.asked("Adults having sex"))

    def test_incidental_wording_does_not_activate_switches(self):
        for subject, name in (("barefoot adults having sex", "feet"), ("sex with feet on the floor", "feet"),
                              ("sex on the sofa beside a table", "furniture"), ("sex while she wears a red dress", "props"),
                              ("sex while she wears heels and stockings", "props")):
            with self.subTest(subject=subject):
                self.assertNotIn(name, self.asked(subject))

    def test_switches_combine_independently(self):
        asked = self.asked("anal and oral BDSM sex with toys, a collar and foot worship at climax")
        self.assertTrue({"kink", "toys", "props", "feet", "finish"} <= asked)
        feet = resolve_route(adult_draft("male", "female", subject="sex with a foot fetish"))
        self.assertIn("feet", feet.asked)
        self.assertNotIn("kink", feet.enabled)
        pet = resolve_route(adult_draft("male", "female", subject="sex with human pet roleplay"))
        self.assertNotIn("kink", pet.enabled)
        self.assertNotIn("furniture", pet.enabled)
        self.assertFalse(pet.kink or pet.owned)

    def test_confirmed_modules_exclude_freely_but_enable_only_with_the_users_words(self):
        modules = {"enabled": ["kink", "feet"], "excluded": ["finish"]}
        route = resolve_route(adult_draft("male", "female", modules=modules))
        self.assertFalse({"kink", "feet"} & route.enabled, "a model-added switch needs the user's words")
        self.assertNotIn("finish", route.enabled)
        supported = resolve_route(adult_draft("male", "female", subject="Adults having kink sex", modules=modules))
        self.assertIn("kink", supported.categories)
        self.assertNotIn("feet", supported.enabled)
        general = resolve_route(adult_draft("male", "female", subject="Two friends at a cafe", modules=modules))
        self.assertEqual(general.profile, "general")
        self.assertFalse(general.kink)
        excluded = resolve_route(adult_draft("male", "female", subject="rough BDSM sex",
                                             modules={"enabled": [], "excluded": ["kink"]}))
        self.assertNotIn("kink", excluded.enabled)

    def test_contradictions_and_impossible_required_acts_become_clarifications(self):
        data = adult_draft("male", "female", modules={"enabled": ["kink"], "excluded": ["kink"]})
        self.assertTrue(any("kink" in question and question.endswith("?")
                            for question in routing_clarifications(data, data["_confirmed_intent"])))
        data = adult_draft("male", "male", subject="Two men having vaginal sex")
        self.assertTrue(any("vaginal anatomy" in question for question in routing_clarifications(data, data["_confirmed_intent"])))
        data = adult_draft("male", "male", subject="Two men having vaginal sex", traits={2: "has a vagina"})
        self.assertEqual(routing_clarifications(data, data["_confirmed_intent"]), [])

    def test_module_lists_validate_known_switches(self):
        self.assertEqual(validate_modules({"enabled": ["kink", "kink"], "excluded": []}), {"enabled": ["kink"], "excluded": []})
        for value in ({"enabled": ["aftercare"], "excluded": []}, {"enabled": []}, {"enabled": "kink", "excluded": []}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_modules(value)


class EquipmentTests(unittest.TestCase):
    def route(self, subject):
        return resolve_route(adult_draft("male", "male", subject=subject))

    def test_kink_without_props_rejects_equipment(self):
        route = self.route("two men in a rough dominant and submissive dynamic")
        self.assertIn("kink", route.categories)
        self.assertNotIn("props", route.enabled)
        self.assertTrue(compatible_entry("one man pins the other down", route))
        for entry in ("wrists tied with rope", "collared and kneeling", "a ballgag in place"):
            with self.subTest(entry=entry):
                self.assertFalse(compatible_entry(entry, route))

    def test_named_props_permit_only_their_family(self):
        route = self.route("two men in bondage tied with rope, dominant and submissive")
        self.assertTrue(compatible_entry("wrists tied with rope", route))
        self.assertFalse(compatible_entry("collared and kneeling", route))
        generic = self.route("two men in a dominant dynamic with BDSM gear")
        self.assertTrue(compatible_entry("collared and kneeling", generic))

    def test_pet_role_without_props_excludes_pet_equipment(self):
        route = self.route("two men having sex with human pet roleplay")
        self.assertTrue(compatible_entry("one crawls like a puppy", route))
        self.assertFalse(compatible_entry("one crawls on a leash", route))


class SelectionTests(unittest.TestCase):
    def test_identical_lines_across_sections_are_offered_once(self):
        catalog = parse_vocabulary("[couple positions]\nFace to face, seated.\n[anal positions]\nFace to face,  seated!\n"
                                   "[oral positions]\nKneeling oral.\n")
        eligible_records, _ = compatible_arrangements(catalog, resolve_route(adult_draft("male", "male")))
        labels = sorted(record.label for record in eligible_records)
        self.assertEqual(len(labels), 2)
        self.assertEqual(sum(label.startswith("Face to face") for label in labels), 1)

    def test_neutral_cast_entries_cross_casts_but_gendered_ones_do_not(self):
        catalog = parse_vocabulary("[man and woman positions]\nPartners face each other, one straddling.\n"
                                   "He kneels behind her.\n")
        for sexes, expected in ((("male", "male"), ["Partners face each other, one straddling."]),
                                (("female", "female"), ["Partners face each other, one straddling."]),
                                (("male", "female"), ["He kneels behind her.", "Partners face each other, one straddling."])):
            with self.subTest(sexes=sexes):
                records, _ = compatible_arrangements(catalog, resolve_route(adult_draft(*sexes)))
                self.assertEqual(sorted(record.label for record in records), expected)

    def test_least_recently_used_spreads_picks_and_resumes_from_saved_ids(self):
        text = "[anal positions]\n" + "\n".join(f"Arrangement {name}." for name in "abcd")
        data = adult_draft("male", "male", subject="Two men having anal sex")
        specs = plan_scene_specs(data, dataset_assignments(data), directions={}, seed=3, catalog=parse_vocabulary(text))
        self.assertEqual(len({spec.catalog_id for spec in specs.values()}), 4)
        used = [specs[1].catalog_id, specs[2].catalog_id, specs[3].catalog_id]
        resumed = plan_scene_specs(data, dataset_assignments(data), directions={}, seed=99,
                                   catalog=parse_vocabulary(text), used=used)
        self.assertEqual(resumed[1].catalog_id, specs[4].catalog_id)

    def test_requested_position_names_lead_and_become_required(self):
        text = "[couple positions]\nDoggy-style, bent over the bed edge.\nSeated embrace.\n"
        data = adult_draft("male", "female", subject="Adults having sex doggy style")
        specs = plan_scene_specs(data, dataset_assignments(data), directions={}, seed=1, catalog=parse_vocabulary(text))
        for spec in specs.values():
            self.assertEqual(dict(spec.choices)["required_position"], "Doggy-style, bent over the bed edge.")
        absent = adult_draft("male", "female", subject="Adults having sex in missionary")
        spec = plan_scene_specs(absent, dataset_assignments(absent), directions={}, seed=1, catalog=parse_vocabulary(text))[1]
        self.assertEqual(dict(spec.choices)["required_position"], "missionary")
        self.assertNotIn("position_candidates", dict(spec.choices))
        self.assertEqual(spec.category, "general")

    def test_requested_extras_are_eligible_without_being_forced(self):
        text = "[couple positions]\nSeated embrace.\n[requested]\nmirror => Facing a mirror together.\n"
        data = {**adult_draft("male", "female", subject="Adults having sex in front of a mirror"), "amount": 6}
        specs = plan_scene_specs(data, dataset_assignments(data), directions={}, seed=1, catalog=parse_vocabulary(text))
        firsts = {dict(spec.choices)["position_candidates"].splitlines()[0] for spec in specs.values()}
        self.assertIn("Facing a mirror together.", firsts)
        self.assertIn("Seated embrace.", firsts)
        self.assertTrue(all("required_position" not in dict(spec.choices) for spec in specs.values()))

    def test_solo_casts_skip_partner_only_entries(self):
        route = resolve_route(adult_draft("female", subject="A woman showing her feet, with toys"))
        for entry in ("feet on the chest during missionary", "toes in his mouth while fucked from behind",
                      "licking a partner's soles"):
            with self.subTest(entry=entry):
                self.assertFalse(compatible_entry(entry, route))
        for entry in ("fucked by a thrusting machine", "pointing her toes toward the camera"):
            with self.subTest(entry=entry):
                self.assertTrue(compatible_entry(entry, route))
        kink = resolve_route(adult_draft("female", subject="A woman masturbating in rope bondage with a ring gag"))
        for entry in ("on the back ankles held by rope while using a toy", "ring gag, mouth held open"):
            with self.subTest(entry=entry):
                self.assertTrue(compatible_entry(entry, kink))

    def test_solo_module_sections_keep_their_module_category(self):
        text = ("[solo positions]\nkneeling alone\n[solo feet positions]\nsoles toward the camera, masturbating\n"
                "[solo kink positions]\nkneeling in rope, waiting\n")
        route = resolve_route(adult_draft("female", subject="A woman masturbating in rope bondage, foot worship"))
        records, _ = compatible_arrangements(parse_vocabulary(text), route)
        self.assertEqual({record.label: record.category for record in records},
                         {"kneeling alone": "solo", "soles toward the camera, masturbating": "feet",
                          "kneeling in rope, waiting": "kink"})

    def test_solo_casts_skip_lines_that_need_an_owner_or_a_second_body(self):
        route = resolve_route(adult_draft("male", subject="A man masturbating, pet play, human furniture, climax"))
        for entry in ("kneeling like a pet at the master's feet", "being walked on a leash around the room",
                      "used as a human chair", "one man cumming on the other's face", "shaking orgasm during scissoring",
                      "both climaxing together", "cum dripping from the ass", "mounted from behind while in pet position"):
            with self.subTest(entry=entry):
                self.assertFalse(compatible_entry(entry, route))
        for entry in ("human pet curled up on a pet bed", "kneeling as a human stool, back flat",
                      "shooting cum onto own stomach while masturbating", "riding a dildo with both hands on the knees"):
            with self.subTest(entry=entry):
                self.assertTrue(compatible_entry(entry, route))

    def test_body_specific_wording_follows_the_cast(self):
        men, women = resolve_route(adult_draft("male", "male")), resolve_route(adult_draft("female", "female"))
        self.assertFalse(compatible_entry("cum on the breasts", men))
        self.assertFalse(compatible_entry("squirting climax while on the back", men))
        self.assertTrue(compatible_entry("squirting climax while on the back", women))
        kink = resolve_route(adult_draft("female", subject="A woman in bondage, sissy maid outfit, chastity"))
        self.assertFalse(compatible_entry("sissy maid on all fours", kink))

    def test_semen_wording_needs_a_penis_in_the_cast(self):
        women = resolve_route(adult_draft("female", "female"))
        self.assertFalse(compatible_entry("cum on the breasts", women))
        self.assertTrue(compatible_entry("cumming while grinding together", women))
        self.assertTrue(compatible_entry("cum on the breasts", resolve_route(adult_draft("male", "female"))))

    def test_unrequested_events_follow_ordinary_positions(self):
        records = [Mock(id=f"finish {n}", category="finish", label=f"finish {n}") for n in range(6)] + [
            Mock(id="anal a", category="anal", label="anal a"), Mock(id="oral a", category="oral", label="oral a")]
        route = resolve_route(adult_draft("male", "male"))
        tiers = position_tiers(records, route, random.Random(3))
        usage = Counter()
        picks = [pick_position(tiers, usage, 2)[0].category for _ in range(2)]
        self.assertEqual(sorted(picks), ["anal", "oral"])

    def test_position_presence_accepts_close_paraphrase(self):
        self.assertIsNone(scene_fact_error("He stands behind her while she is bent forward over the table, vaginal sex.",
                                           "standing bent over", ["vaginal"]))
        self.assertIsNotNone(scene_fact_error("They kiss on the sofa, vaginal sex.", "standing bent over", ["vaginal"]))

    def test_model_written_facts_do_not_trigger_requested_extras(self):
        text = "[couple positions]\nSeated embrace.\n[requested]\n(?i)multiple|group => everyone around the center partner\n"
        data = adult_draft("male", "male", subject="Two men having anal sex")
        data["_confirmed_intent"]["hard"] = [{"scope": "all_outputs", "text": "Multiple characters visibility: show everyone."}]
        records, _ = compatible_arrangements(parse_vocabulary(text), resolve_route(data))
        self.assertEqual([record.label for record in records], ["Seated embrace."])

    def test_group_wording_needs_three_or_more_people(self):
        for entry in ("creampie while being spit-roasted", "one partner cumming while the others continue",
                      "center partner covered in cum from the group"):
            with self.subTest(entry=entry):
                self.assertFalse(compatible_entry(entry, resolve_route(adult_draft("male", "male"))))
                self.assertTrue(compatible_entry(entry, resolve_route(adult_draft("male", "male", "male"))))

    def test_group_alternatives_prefer_different_activities(self):
        records = [Mock(id=name, category=category, label=name) for name, category in
                   (("anal a", "anal"), ("anal b", "anal"), ("oral a", "oral"))]
        record, alternatives, _ = pick_position(((), (), (), tuple(records)), Counter(), 3)
        self.assertEqual(record.category, "anal")
        self.assertEqual(alternatives[0].category, "oral")

    def test_a_rejected_position_is_not_offered_again_in_the_batch(self):
        text = "[anal positions]\n" + "\n".join(f"Arrangement {name}." for name in "abcdefgh")
        data = {**adult_draft("male", "male", subject="Two men having anal sex"), "amount": 10}
        specs = list(plan_scene_specs(data, dataset_assignments(data), directions={}, seed=5,
                                      catalog=parse_vocabulary(text)).values())
        offered = []
        def generate(instruction):
            if instruction.diagnostic_stage == "dataset:planning:setting":
                return json.dumps([{"index": row["index"], "setting": "a room"}
                                   for row in json.loads(instruction.user_message)["assignments"]])
            rows = json.loads(instruction.user_message)["assignments"]
            offered.extend(row["optional_suggestions"].get("position_candidates", "") for row in rows)
            return json.dumps([{"index": row["index"], "action": row["action"], "setting": row["setting"] or "a room",
                "participants": [{key: item[key] for key in ("id", "role", "pose", "location", "support")}
                                 for item in row["participants"]], "contacts": [],
                "position": "" if row["index"] <= 5 else planned_facts(row)["position"],
                "activities": [{"activity": "anal", "participants": ["P1", "P2"]}]} for row in rows])
        session = Mock()
        session.generate.side_effect = generate
        frozen, errors = propose_scene_specs(session, data, specs, lambda: None)
        self.assertEqual(errors, {})
        rejected = {line for block in offered[:5] for line in block.splitlines()}
        later = {line for block in offered[5:] for line in block.splitlines()}
        self.assertTrue(rejected)
        self.assertFalse(rejected & later)


class SceneFactTests(unittest.TestCase):
    def provisional(self, *sexes, subject="Adults having anal sex", text="[anal positions]\nDoggy-style, anal.\n"):
        data = adult_draft(*sexes, subject=subject)
        return plan_scene_specs(data, dataset_assignments(data), directions={}, seed=2, catalog=parse_vocabulary(text))[1]

    def candidate(self, spec, **changes):
        return {"index": spec.index, "action": "Adults share the scene.", "setting": "a room",
                "participants": [{"id": item.id, "role": "", "pose": "kneeling", "location": "", "support": "knees_on_floor"}
                                 for item in spec.participants], "contacts": [],
                "position": "Doggy-style, anal.", "activities": [{"activity": "anal", "participants": ["P1", "P2"]}], **changes}

    def test_freezing_keeps_the_selected_position_and_activities(self):
        spec = self.provisional("male", "male")
        frozen = freeze_scene_spec(spec, self.candidate(spec))
        self.assertEqual(frozen.position, "Doggy-style, anal.")
        self.assertEqual(frozen.activities, (("anal", ("P1", "P2")),))
        self.assertNotIn("eligible_activities", dict(frozen.choices))
        self.assertEqual(SceneSpec.from_dict(frozen.to_dict()), frozen)
        self.assertEqual(freeze_scene_spec(spec, self.candidate(spec, position="Doggy-style")).position, "Doggy-style, anal.")

    def test_freezing_rejects_lost_or_impossible_facts(self):
        spec = self.provisional("male", "male")
        for changes in ({"position": "Missionary."}, {"activities": []},
                        {"activities": [{"activity": "vaginal", "participants": ["P1", "P2"]}]},
                        {"activities": [{"activity": "anal", "participants": ["P1", "P9"]}]},
                        {"contacts": [{"source": "P1.penis", "target": "P2.vagina"}]}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                freeze_scene_spec(spec, self.candidate(spec, **changes))
        missing = {key: value for key, value in self.candidate(spec).items() if key != "activities"}
        with self.assertRaises(ValueError):
            freeze_scene_spec(spec, missing)

    def test_explicit_supports_take_precedence_over_a_mismatched_label(self):
        # Gemma labels a doggy-style bottom "knees_on_floor" while the explicit support puts her knees on the bed.
        spec = self.provisional("male", "female", subject="A man and a woman having anal sex doggy style")
        bed = [{"source": "P2.knees", "target": "setting.bed"}, {"source": "P1.knees", "target": "setting.bed"}]
        frozen = freeze_scene_spec(spec, self.candidate(spec, supports=bed))
        self.assertEqual({item.id: item.support for item in frozen.participants}, {"P1": "knees_on_bed", "P2": "knees_on_bed"})
        self.assertEqual(set(frozen.supports), {Contact("P1.knees", "setting.bed"), Contact("P2.knees", "setting.bed")})
        # A held body keeps the partner who holds it.
        held = freeze_scene_spec(spec, self.candidate(spec, supports=[{"source": "P2.knees", "target": "P1.body"}]))
        self.assertEqual(dict((item.id, item.support) for item in held.participants)["P2"], "supported_at_knees_by_P1")

    def test_a_locked_support_label_still_rejects_a_contradicting_support(self):
        spec = self.provisional("male", "female", subject="A man and a woman having anal sex doggy style")
        locked = replace(spec, participants=tuple(replace(item, support="knees_on_floor") for item in spec.participants),
                         locked=(*spec.locked, "participant:P2:support"))
        with self.assertRaises(ValueError):
            freeze_scene_spec(locked, self.candidate(locked, supports=[{"source": "P2.knees", "target": "setting.bed"}]))

    def test_a_requested_named_position_keeps_its_activity(self):
        spec = self.provisional("male", "male", subject="Two men having sex doggy style",
                                text="[anal positions]\nDoggy-style, bent over the bed edge.\n")
        self.assertEqual(dict(spec.choices)["required_position"], "Doggy-style, bent over the bed edge.")
        with self.assertRaises(ValueError):
            freeze_scene_spec(spec, self.candidate(spec, position="Doggy-style", activities=[]))
        frozen = freeze_scene_spec(spec, self.candidate(spec, position="Doggy-style"))
        self.assertEqual(frozen.position, "Doggy-style, bent over the bed edge.")

    def test_group_scenes_can_combine_activities_across_participants(self):
        spec = self.provisional("male", "female", "male", subject="Three adults having anal and oral sex",
                                text="[three positions]\nAll three on the bed.\n")
        frozen = freeze_scene_spec(spec, self.candidate(spec, position="All three on the bed.", activities=[
            {"activity": "anal", "participants": ["P1", "P2"]}, {"activity": "oral", "participants": ["P3", "P2"]}]))
        self.assertEqual({name for name, _ in frozen.activities}, {"anal", "oral"})
        with self.assertRaises(ValueError):
            freeze_scene_spec(spec, self.candidate(spec, position="All three on the bed.",
                                                   activities=[{"activity": "anal", "participants": ["P1", "P2"]}]))

    def test_saved_plans_without_facts_keep_their_signature(self):
        spec = self.provisional("male", "male")
        plain = replace(spec, choices=(), state="frozen")
        self.assertNotIn("position", plain.to_dict())
        self.assertEqual(SceneSpec.from_dict(plain.to_dict()).signature, plain.signature)

    def test_leading_activity_or_theme_words_are_not_position_names(self):
        from goated_prompter.features.dataset.quality import position_name
        self.assertEqual(position_name("anal, standing bent over"), "standing bent over")
        self.assertEqual(position_name("collared, kneeling oral"), "kneeling oral")
        self.assertEqual(position_name("anal doggy style, on the bed"), "doggy style")
        self.assertIsNone(scene_fact_error("Doggy-style anal sex on the bed.", "anal doggy style, on the bed", ["anal"]))
        self.assertEqual(position_name("anal, sitting on the lap facing away from the partner"), "")
        self.assertIsNotNone(scene_fact_error("They have anal sex.", "anal, standing bent over", ["anal"]))
        self.assertIsNone(scene_fact_error("Standing bent over the desk, anal sex.", "anal, standing bent over", ["anal"]))

    def test_presence_check_requires_the_position_name_or_a_synonym_and_each_activity(self):
        self.assertIsNone(scene_fact_error("He takes her doggy style, anal, on the bed.", "Doggy-style, anal.", ["anal"]))
        self.assertIsNone(scene_fact_error("On all fours from behind, anal sex.", "Doggy-style, anal.", ["anal"]))
        self.assertIn("Doggy-style", scene_fact_error("They kneel together, anal.", "Doggy-style, anal.", ["anal"]))
        self.assertIn("oral", scene_fact_error("Doggy style, anal.", "Doggy-style", ["anal", "oral"]))
        self.assertIsNone(scene_fact_error("Doggy style with anal while her mouth is on him.", "Doggy-style", ["anal", "oral"]))
        self.assertIn("vaginal", scene_fact_error("Doggy style with anal and vaginal sex.", "Doggy-style", ["anal"]))
        for text in ("Doggy style, he thrusts into her slowly.", "Doggy style, deep inside her.", "Doggy style; he penetrates her."):
            with self.subTest(text=text):
                self.assertIsNone(scene_fact_error(text, "Doggy-style", ["vaginal"]))


class WriterEnforcementTests(unittest.TestCase):
    def scene(self):
        data = adult_draft("male", "male", subject="Two men having anal sex", trigger="ohwx_person")
        row = planned_scene(data, catalog=parse_vocabulary("[anal positions]\nDoggy-style, anal.\n"),
                            scene="Two men, doggy style, anal.")
        spec = replace(SceneSpec.from_dict(row["scene_spec"]), choices=(), position="Doggy-style, anal.",
                       activities=(("anal", ("P1", "P2")),))
        return data, checked_scene(row, spec=spec)

    def test_writer_is_told_the_selected_facts(self):
        data, scene = self.scene()
        instruction = dataset_instruction(GoatedPrompterRequest(idea=data["subject"]), data, 1, plan_item=scene)
        self.assertIn("MUST DEPICT (selected scene facts): Position: Doggy-style, anal. (name it as \"Doggy-style\")",
                      instruction.system_message)
        self.assertIn("anal", instruction.system_message.split("MUST DEPICT", 1)[1])

    def test_a_lost_position_gets_one_targeted_retry_then_fails(self):
        data, scene = self.scene()
        instruction = dataset_instruction(GoatedPrompterRequest(idea=data["subject"]), data, 1, plan_item=scene)
        kept = "ohwx_person and another adult man, doggy style, anal sex in a dim room."
        lost = "ohwx_person and another adult man kneel together in a dim room."
        session = Mock()
        checked_writer_responses(session, [lost, kept], [scene])
        service = DatasetService({}, lambda: None)
        self.assertEqual(service._generate(session, instruction, data, 1, lambda _: None, scene, retries=1), kept)
        retry = [call.args[0] for call in session.generate.call_args_list][1]
        self.assertIn('named "Doggy-style"', retry.system_message)
        session = Mock()
        checked_writer_responses(session, [lost, lost], [scene])
        with self.assertRaises(BackendGenerationError):
            service._generate(session, instruction, data, 1, lambda _: None, scene, retries=1)
        self.assertEqual(session.generate.call_count, 2)


class FidelityAuditTests(unittest.TestCase):
    def test_audit_counts_checks_rewrites_and_cost_without_changing_outcomes(self):
        data, scene = WriterEnforcementTests().scene()
        instruction = dataset_instruction(GoatedPrompterRequest(idea=data["subject"]), data, 1, plan_item=scene)
        session = Mock()
        checked_writer_responses(session, ["ohwx_person and another adult man, doggy style, anal sex."], [scene])
        service = DatasetService({}, lambda: None)
        service._generate(session, instruction, data, 1, lambda _: None, scene, retries=0)
        audit = service.fidelity_audit
        self.assertEqual((audit["checked"], audit["passed_unchanged"], audit["flagged"], audit["rewritten"], audit["check_calls"]),
                         (1, 1, 0, 0, 1))
        self.assertEqual(audit["drafts"][0]["verdict"], "valid")
        self.assertGreaterEqual(audit["check_seconds"], 0)


if __name__ == "__main__":
    unittest.main()
