"""Plain TXT vocabulary routing, using synthetic entries only."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from goated_prompter.features.dataset.brainstorm import dataset_routing, sexual_positions
from goated_prompter.features.dataset.batch_planner import plan_scene_specs, planning_instruction, freeze_scene_spec
from goated_prompter.features.dataset.assignments import dataset_assignments
from goated_prompter.features.dataset.compatibility import position_sections, styling_sections
from goated_prompter.features.dataset.private_vocabulary import SECTIONS, load_vocabulary, parse_vocabulary, private_rules
from goated_prompter.features.dataset.routing import resolve_route
from tests.helpers import dataset_understanding_fixture
from tests.support.dataset import valid_draft


def adult_draft(*sexes, subject="Adults having sex", **changes):
    characters = [{"name": f"adult {index}", "count": 1, "sex": sex, "kind": "human",
                   "origin": "described", "series": "", "traits": ""}
                  for index, sex in enumerate(sexes, 1)]
    brief = dataset_understanding_fixture(character_count=len(sexes), characters=characters)
    return valid_draft(subject=subject, trigger="", amount=4, trigger_type="Multiple characters",
                       _confirmed_intent=brief, **changes)


class TxtVocabularyTests(unittest.TestCase):
    def positions(self, data, text):
        with patch("goated_prompter.features.dataset.brainstorm.load_vocabulary",
                   return_value=parse_vocabulary(text)):
            return sexual_positions(data)

    def test_plain_positions_are_usable_without_conversion_or_structure_warnings(self):
        text = "[two men positions]\nTwo adult men sit facing each other.\n"
        catalog = parse_vocabulary(text)
        self.assertFalse(catalog.diagnostics)
        self.assertEqual(self.positions(adult_draft("male", "male"), text),
                         ("Two adult men sit facing each other.",))

    def test_broad_male_request_offers_ordinary_acts_not_specialized_themes(self):
        text = ("[oral positions]\nKneeling oral.\n[anal positions]\nSeated anal.\n"
                "[feet positions]\nFoot worship.\n[kink positions]\nRestrained pose.\n")
        self.assertEqual(set(self.positions(adult_draft("male", "male"), text)),
                         {"Kneeling oral.", "Seated anal."})

    def test_routing_counts_filtered_prose_without_exposing_entries_or_structure_warnings(self):
        catalog = parse_vocabulary('[oral positions]\nPRIVATE_SENTINEL cunnilingus.\nSeated oral contact.\n')
        with patch('goated_prompter.features.dataset.brainstorm.load_vocabulary', return_value=catalog):
            routing = dataset_routing(adult_draft('male', 'male'))
        diagnostics = routing[0]['vocabulary']
        self.assertEqual((diagnostics['loaded'], diagnostics['eligible'], diagnostics['rejected']), (2, 1, 1))
        self.assertFalse(diagnostics['unresolved_constraints'])
        self.assertNotIn('PRIVATE_SENTINEL', json.dumps(routing))
        self.assertNotIn('unresolved_structure', json.dumps(routing))

    def test_solo_does_not_require_toys_or_add_a_partner(self):
        text = ("[solo positions]\nSeated self-pleasure.\n[oral positions]\nKneeling oral.\n"
                "[toys]\nSolo vibrator use.\n[couple positions]\nPartners embrace.\n")
        self.assertEqual(self.positions(adult_draft("female", subject="One adult woman masturbating"), text),
                         ("Seated self-pleasure.",))

    def test_character_pools_match_each_cast_size_and_pairing(self):
        cases = [(('male',), {'solo positions'}),
                 (('male', 'male'), {'couple positions', 'two men positions'}),
                 (('female', 'female'), {'couple positions', 'two women positions'}),
                 (('female', 'male'), {'couple positions', 'man and woman positions'}),
                 (('male', 'female', 'male'), {'three positions'}),
                 (('female',) * 5, {'group positions'})]
        cast_sections = {'solo positions', 'couple positions', 'two men positions', 'two women positions',
                         'man and woman positions', 'three positions', 'group positions'}
        for sexes, expected in cases:
            with self.subTest(sexes=sexes):
                self.assertEqual(position_sections(resolve_route(adult_draft(*sexes))) & cast_sections, expected)

    def test_female_activities_do_not_invent_male_anatomy_or_mandatory_toys(self):
        text = ("[oral positions]\nCunnilingus while seated.\nBlowjob while seated.\n"
                "[vaginal positions]\nVaginal contact using fingers.\nVaginal penetration with his penis.\n"
                "[anal positions]\nAnal contact using hands.\nAnal contact with a dildo.\n")
        self.assertEqual(set(self.positions(adult_draft('female', 'female'), text)),
                         {'Cunnilingus while seated.', 'Vaginal contact using fingers.', 'Anal contact using hands.'})

    def test_explicit_anatomy_exception_is_bound_to_its_actual_owner(self):
        text = "[vaginal positions]\nVaginal penetration with his penis.\nVaginal penetration with her penis.\n"
        data = adult_draft('male', 'male', subject='Two adult men having vaginal sex')
        data['_confirmed_intent']['characters'][1]['traits'] = 'has a vagina, no penis'
        self.assertEqual(self.positions(data, text), ('Vaginal penetration with his penis.',))
        women = adult_draft('female', 'female', subject='Two adult women having vaginal sex')
        women['_confirmed_intent']['characters'][0]['traits'] = 'has a penis'
        self.assertEqual(self.positions(women, text), ('Vaginal penetration with her penis.',))

    def test_generic_penetration_uses_explicit_anatomy_not_only_sex_labels(self):
        text = '[vaginal positions]\nVaginal penetration with his penis.\n'
        data = adult_draft('male', 'male', subject='Two adult men having intercourse')
        data['_confirmed_intent']['characters'][1]['traits'] = 'has a vagina, no penis'
        self.assertEqual(self.positions(data, text), ('Vaginal penetration with his penis.',))

    def test_mixed_groups_filter_the_participants_in_each_activity_not_the_whole_cast(self):
        text = ("[three positions]\nThree adults sit together.\n"
                "[vaginal positions]\nOne man and one woman share vaginal contact while another adult rests.\n"
                "Two men and two women share vaginal contact.\n"
                "[oral positions]\nTwo women share cunnilingus while one man rests.\n")
        positions = set(self.positions(adult_draft('male', 'female', 'male'), text))
        self.assertEqual(positions, {'Three adults sit together.',
                         'One man and one woman share vaginal contact while another adult rests.'})

    def test_large_groups_can_select_an_activity_for_a_subset_without_dropping_cast(self):
        text = ("[group positions]\nFour adults arranged together.\n"
                "[oral positions]\nA woman and a man share oral contact as the others rest.\n")
        data = adult_draft('male', 'female', 'female', 'male')
        self.assertEqual(len(self.positions(data, text)), 2)
        specs = self.plan(data, text)
        self.assertTrue(all(len(spec.participants) == 4 for spec in specs.values()))

    def test_each_optional_section_has_an_independent_activation_rule(self):
        broad = resolve_route(adult_draft('male', 'female'))
        active = position_sections(broad) | {section for sections in styling_sections(broad).values() for section in sections} | {'rules'}
        self.assertFalse(active & {'props', 'toys', 'kink positions', 'pet positions', 'furniture positions',
                                  'feet positions', 'finish positions', 'aftercare positions'})
        requests = {'kink': 'sex in bondage', 'pet': 'sex with human pet roleplay',
                    'furniture': 'sex with a human furniture theme', 'feet': 'foot worship',
                    'toys': 'sex with optional toys', 'finish': 'sex at climax', 'aftercare': 'sexual aftercare'}
        covered = set(active)
        for theme, subject in requests.items():
            route = resolve_route(adult_draft('male', 'female', subject=subject))
            selected = position_sections(route) | {section for sections in styling_sections(route).values() for section in sections}
            self.assertIn('toys' if theme == 'toys' else theme + ' positions', selected)
            if theme == 'kink':
                self.assertFalse(selected & {'pet mood', 'pet interaction', 'pet positions', 'furniture positions', 'feet positions', 'toys'})
            covered.update(selected)
        covered.update(position_sections(resolve_route(adult_draft('male', subject='Solo adult masturbating in bondage'))))
        covered.update({'ownership rules', 'requested'})
        for sexes in [('male', 'male'), ('female', 'female'), ('female', 'male', 'male'), ('female',) * 5]:
            route = resolve_route(adult_draft(*sexes))
            covered.update(position_sections(route))
            covered.update(section for sections in styling_sections(route).values() for section in sections)
        self.assertEqual(covered, set(SECTIONS))

    def test_excluded_themes_and_activities_stay_inactive_even_when_other_themes_are_active(self):
        text = ("[anal positions]\nSeated anal contact.\n[oral positions]\nSeated oral contact.\n"
                "[kink positions]\nBondage pose.\n[pet positions]\nHuman pet play.\n"
                "[toys]\nAnal toy use.\n[requested]\nleash => Human pet play.\n")
        data = adult_draft('male', 'male', subject='Two adult men having anal sex in bondage',
                           constraints='No oral, no toys, no pet play, no leash.')
        self.assertEqual(set(self.positions(data, text)), {'Seated anal contact.', 'Bondage pose.'})

    def test_solo_themes_cannot_smuggle_in_a_partner(self):
        text = ("[solo positions]\nSolo self-pleasure.\n[solo kink positions]\nSolo restrained self-pleasure.\n"
                "A partner restrains the solo adult.\n[pet positions]\nSolo human pet roleplay.\n"
                "Partners perform human pet play.\n[toys]\nSolo toy use.\n")
        data = adult_draft('female', subject='Solo adult woman masturbating with bondage, human pet roleplay and optional toys')
        self.assertEqual(set(self.positions(data, text)), {'Solo self-pleasure.', 'Solo restrained self-pleasure.',
                                                         'Solo human pet roleplay.', 'Solo toy use.'})

    def plan(self, data, text):
        return plan_scene_specs(data, dataset_assignments(data), directions={}, seed=7, catalog=parse_vocabulary(text))

    def test_planner_gets_few_alternatives_for_one_act_and_one_universal_setting(self):
        text = '[oral positions]\n' + '\n'.join(f'Oral arrangement {index}.' for index in range(100))
        text += '\n[anal positions]\nSeated anal contact.\n[setting]\nQuiet room.\n[mood]\nTender mood.\n'
        data = adult_draft('male', 'male', subject='Two adults having oral sex')
        specs = self.plan(data, text)
        for spec in specs.values():
            choices = dict(spec.choices)
            self.assertEqual(choices['activity'], 'oral')
            self.assertEqual(len(choices['position_candidates'].splitlines()), 3)
            self.assertEqual(choices['setting'], 'Quiet room.')
            self.assertEqual(choices['mood'], 'Tender mood.')
            self.assertEqual(spec.locked, ('hard',))
            self.assertEqual(spec.contacts, ())
            self.assertTrue(all(not item.pose and not item.support for item in spec.participants))
        instruction = planning_instruction(data, list(specs.values()))
        self.assertLess(instruction.user_message.count('Oral arrangement'), 13)
        self.assertNotIn('Seated anal contact', instruction.user_message)
        self.assertIn('ONE compatible primary', instruction.system_message)

    def test_contradictory_actions_are_filtered_in_positions_and_styling(self):
        text = ('[oral positions]\nSeated oral contact.\nOral and anal at once.\n'
                '[interaction]\nShare oral contact.\nShare anal contact.\n'
                '[setting]\nQuiet room.\n')
        data = adult_draft('male', 'female', subject='Two adults having only oral sex')
        self.assertEqual(self.positions(data, text), ('Seated oral contact.',))
        for spec in self.plan(data, text).values():
            self.assertEqual(dict(spec.choices)['interaction'], 'Share oral contact.')
            self.assertNotIn('anal', json.dumps(spec.to_dict()).casefold())

    def test_explicit_combination_stays_available_without_forcing_it_on_broad_requests(self):
        text = '[three positions]\nThree adults combine oral and vaginal contact.\n'
        data = adult_draft('male', 'female', 'female', subject='Three adults combine oral and vaginal contact')
        self.assertEqual(len(self.positions(data, text)), 1)
        self.assertFalse(self.positions(adult_draft('male', 'female', 'female'), text))

    def test_universal_setting_and_mood_are_used_for_each_ordinary_activity(self):
        text = ('[oral positions]\nOral contact.\n[anal positions]\nAnal contact.\n'
                '[vaginal positions]\nVaginal contact.\n[setting]\nQuiet room.\n[mood]\nTender mood.\n')
        for act in ('oral', 'anal', 'vaginal'):
            data = adult_draft('male', 'female', subject=f'Two adults having {act} sex')
            choices = dict(self.plan(data, text)[1].choices)
            self.assertEqual((choices['setting'], choices['mood']), ('Quiet room.', 'Tender mood.'))

    def test_clothing_and_excluded_settings_are_filtered_before_planning(self):
        text = ('[solo positions]\nSolo self-pleasure.\n[clothing]\nNaked.\nWearing a shirt.\n'
                '[setting]\nA beach.\nA quiet room.\n')
        for wording, expected in [('fully naked', 'Naked.'), ('nude', 'Naked.'), ('fully clothed', 'Wearing a shirt.')]:
            data = adult_draft('female', subject=f'An adult woman {wording} while masturbating', constraints='No beach.')
            choices = dict(self.plan(data, text)[1].choices)
            self.assertEqual(choices['clothing'], expected)
            self.assertEqual(choices['setting'], 'A quiet room.')

    def test_freezing_resolves_guidance_without_locking_optional_activity_or_position(self):
        data = adult_draft('female', subject='Solo adult woman masturbating')
        provisional = self.plan(data, '[solo positions]\nSeated self-pleasure.\n')[1]
        candidate = {'index': 1, 'action': 'An adult woman chooses standing self-pleasure.',
                     'participants': [{'id': 'P1', 'role': 'participant', 'pose': 'standing',
                                       'location': 'center', 'support': 'feet_on_floor'}],
                     'contacts': [], 'setting': 'A room.'}
        frozen = freeze_scene_spec(provisional, candidate)
        self.assertEqual(frozen.action, candidate['action'])
        self.assertEqual(frozen.locked, ('hard',))
        self.assertNotIn('position_candidates', dict(frozen.choices))
        self.assertNotIn('activity', dict(frozen.choices))

    def test_batch_avoids_repeated_position_setting_pairs_until_combinations_are_exhausted(self):
        text = ('[solo positions]\nSeated self-pleasure.\nStanding self-pleasure.\n'
                '[setting]\nRoom alpha.\nRoom beta.\n')
        specs = self.plan(adult_draft('female', subject='Solo adult woman masturbating'), text)
        pairs = [(dict(spec.choices)['position_candidates'].splitlines()[0], dict(spec.choices)['setting'])
                 for spec in specs.values()]
        self.assertEqual(len(set(pairs)), 4)

    def test_original_txt_and_stale_sidecars_are_left_unchanged_and_only_txt_is_loaded(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'sexual.txt'
            original = b'[solo positions]\r\nSeated self-pleasure.\r\n'
            path.write_bytes(original)
            sidecar = path.with_name('sexual.txt.catalog.json')
            sidecar.write_text('not a catalog', encoding='utf-8')
            loaded = load_vocabulary(path)
            self.assertEqual(loaded['solo positions'], ('Seated self-pleasure.',))
            self.assertFalse(loaded.diagnostics)
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(sidecar.read_text(encoding='utf-8'), 'not a catalog')
            path.write_bytes(original + b'Standing self-pleasure.\r\n')
            self.assertEqual(len(load_vocabulary(path)['solo positions']), 2)

    def test_rule_guidance_is_bounded_and_specialized_rules_do_not_activate_themes(self):
        catalog = parse_vocabulary('[rules]\n' + '\n'.join(f'General guidance {index}.' for index in range(100))
                                   + '\nUse pet play.\n')
        with patch('goated_prompter.features.dataset.private_vocabulary.load_vocabulary', return_value=catalog):
            guidance = private_rules(adult_draft('male', 'male'))
        self.assertEqual(guidance.count('- General guidance'), 4)
        self.assertNotIn('Use pet play', guidance)

    def test_rule_guidance_is_scoped_to_only_the_guided_assignments_it_fits(self):
        data = adult_draft('male', 'male', source_mode='guided', inputs='Oral sex\nAnal sex')
        catalog = parse_vocabulary('[rules]\nUse oral contact.\nUse anal contact.\n')
        with patch('goated_prompter.features.dataset.private_vocabulary.load_vocabulary', return_value=catalog):
            guidance = private_rules(data)
        self.assertIn('Use oral contact. (assignment indexes: 1, 3)', guidance)
        self.assertIn('Use anal contact. (assignment indexes: 2, 4)', guidance)

    def test_finish_and_aftercare_guidance_matches_the_requested_moment(self):
        text = ('[oral positions]\nOral contact.\n[finish positions]\nAdults at climax.\n'
                '[aftercare positions]\nAdults share aftercare.\n')
        for moment, expected in [('sex at climax', 'finish'), ('sexual aftercare', 'aftercare')]:
            data = adult_draft('male', 'female', subject=f'Adults sharing {moment}')
            self.assertTrue(all(spec.category == expected for spec in self.plan(data, text).values()))
        self.assertEqual(self.positions(adult_draft('male', 'female'), text), ('Oral contact.',))
        oral_finish = self.plan(adult_draft('male', 'female', subject='Adults having oral sex at climax'), text)[1]
        self.assertEqual(oral_finish.category, 'finish')
        self.assertEqual(dict(oral_finish.choices)['activity'], 'oral')

    def test_directly_requested_solo_activity_activates_without_a_generic_nsfw_keyword(self):
        text = '[solo positions]\nSolo self-pleasure.\n[toys]\nSolo vibrator use.\n'
        data = adult_draft('female', subject='One adult woman using a vibrator')
        self.assertEqual(set(self.positions(data, text)), {'Solo self-pleasure.', 'Solo vibrator use.'})

    def test_general_planning_does_not_gain_private_or_new_styling_choices(self):
        data = adult_draft('male', 'female', subject='Two adults at the climax of a staged play')
        directions = {1: {'setting': 'Unused general setting', 'interaction': 'Unused general interaction',
                          'clothing': 'Unused clothing', 'framing': 'Full body'}}
        specs = plan_scene_specs(data, dataset_assignments(data), directions=directions, catalog=parse_vocabulary('[setting]\nPRIVATE_SENTINEL\n'))
        self.assertEqual(specs[1].route, 'general')
        self.assertEqual(dict(specs[1].choices), {'framing': 'Full body'})
        self.assertFalse(specs[1].private_vocabulary)
