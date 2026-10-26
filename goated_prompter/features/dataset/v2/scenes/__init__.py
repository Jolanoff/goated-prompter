"""Section 2 — Scenes: the scene writer turns the confirmed brief into one scene per image, in batches of BATCH.

Its prompt holds the user request, the approved requirements (rules, Understanding, style) and, when the user picked
vocabulary packs for the run, a SELECTED VOCABULARY section: only the categories that have a selected pack, each with
its Core instruction and the entries of those packs (vocabulary/catalog.py), shuffled for every batch with a random
generator seeded by the run's seed, so each seed leads the writer to different entries first. Vocabulary is used only
when the scenes are invented (source "random"); with the user's own scene ideas (source "guided") no vocabulary is
sent. With no pack selected the prompt has no vocabulary section. The run's Director decides what each scene
emphasizes (request.director_emphasis); the final prompt writes the decided scene without it.

Actions & Poses: when that category has a selected pack, one call first keeps only the entries that fit the request
and the cast (fitting_entries; every entry when that call fails). Only those reach the writer: every image is dealt a
different one from a seeded shuffle (deal_entries) and every scene names the entry it is built on ("entry", copied
word for word); the writer keeps the dealt entry unless it cannot fit the cast. Code checks that the entry is one of
the fitting entries and asks again otherwise (the last round keeps the image). The writer is told how many images may
share an entry (ENTRY_CAP: two, or more when fewer entries fit than images are requested) and how many already do; an
entry used more often is kept, never asked again. When no entry fits, the writer gets no Actions & Poses vocabulary
and builds a logical pose for the request.

Places (places.py): unless the request keeps the place without words for it, every image is dealt one place from the
selected Spaces packs or, after them, the always-on built-in places; the scene is built there (PLACE_RULE) and a scene
built elsewhere is asked again. The groups whose words the request says most often are chosen (its place words when
it keeps the place, else the whole request); a fitting call reads the group names when none matches.

Optional pack features: entries that need more people than the cast (a pack's "people") are removed before anything
else (fit_cast), and so are entries with a slot ("holding [Kitchen-and-Dining]") that names a pack or category the run
did not select (only_fillable). A slot that is kept stays as written: the writer sees the pack it names among the
selected vocabulary and takes a fitting entry from it (a live run merged them correctly; filling slots in code gave
more retries). Packs without them are used exactly as before.

A scene has subjects (per character: skin, build, hair, detail, expression; a known character, which the
image model draws from its name or trigger, has only expression), position (per character, with their place in the
frame and every body part named with its owner), actions, space, camera and extras. Every fact is written once: the
actions own the act, each position places one person around it (pose, facing, weight, hands) without repeating it,
the camera owns what is visible, and extras hold only visible details, the clothing and the light source among them.
An Actions & Poses entry is the image's act and arrangement, used as written: the writer maps its people to the
character labels (and their gender) and adapts only what conflicts with the request, the cast or the kept place.

Code checks the shape of each answer (every section filled, exactly the character labels, no phrase from the avoid
list), that the actions name every person (unnamed_people), so no entry is copied with its placeholder people, and
that a known character is framed at least head to hips with the face visible (framing_problems). Only a scene that
would ruin the image is asked again: a repeated place, camera, look, entry or dealt frame never is (a live run asked
seven of ten images again for the place and camera the request kept), since variety is the prompt's and the
vocabulary's job. The scene says each fact once (the act in the actions only), so code no longer reads or edits body
parts in it. The last round keeps what it gets rather than lose the image; images still missing are asked again, up to
ROUNDS times per batch.
Later batches see what earlier images used as lists (already_used), not as scenes to imitate.

Slot identity: image N is slot N from start to finish; a failed slot never shifts its siblings. result["slots"] has
one record per requested image: {"slot", "status": "written" | "failed", "input", "concept" (None: there is no
separate planning step), "stage": None or "scene", "reasons", "tries"}. on_slot("description", slot, scene) is called
as each scene is finished.
"""

from contextlib import closing, nullcontext
import random

from .....backends.factory import create_backend
from .....contracts import effective_model_family
from .....director_profiles import resolve_director_config
from ....vocabulary.catalog import catalog_for, selected_vocabulary, record as selection_record, validate_selection, vocabulary_prompt
from ....vocabulary.embeddings import embeddings_for
from ....vocabulary.retrieval import fit_scores, groups_of, telling_words
from ....vocabulary.selection import deal_spread, pair
from ..understanding import validate_brief

from ..consistency import levels, locked_categories
from .checks import _summary, avoid_patterns, retire_fields, scene_errors
from .entries import _entry_key, deal_frames, _only, _shuffled, cast_size, deal_entries, deal_hands, entry_cap, fit_cast, fitting_entries, requested_entries, requested_words, required_frame
from .request import _system, compose_instruction, compose_message, deals_frames, known_labels, slot_inputs, subject_fields, trigger_notes, varied_labels
from .settings import ACTIONS_CATEGORY, BATCH, EARLIER, KNOWN_SUBJECT_FIELDS, ROUNDS, SECTIONS, SUBJECT_FIELDS, VOCABULARY_SAMPLE
from .places import SPACES, place_plan
from .slots import only_fillable
from .texts import COMPOSE_SYSTEM, ENTRY_FIT_SYSTEM, ENTRY_RULE, GUIDED_RULE, NO_PEOPLE_RULE, NSFW_RULE, SFW_RULE, VOCABULARY_RULES
from .writer import _compose


def write_scenes(config, request, brief, *, checkpoint=lambda: None, progress=print, on_slot=lambda *_: None,
                 vocabulary=None, catalog=None):
    """One composed scene per image.

    vocabulary: the run's selection {"packs": [pack ids]} (None: no packs).
    catalog: the vocabulary catalog (default: read from disk now, packs only when the run selects any; a pack that
    disappeared since Confirm fails the run before any inference)."""
    brief = validate_brief(brief)
    total = brief["input"]["amount"]
    if type(total) is not int or total < 1:
        raise ValueError("The brief has no image amount.")
    inputs = slot_inputs(brief)
    guided = brief["input"].get("source_mode") == "guided"
    vocabulary = None if guided else vocabulary  # the user's own scene ideas use no vocabulary
    catalog = catalog if catalog is not None else catalog_for(vocabulary)
    selection = validate_selection(catalog, vocabulary)
    groups = only_fillable(fit_cast(selected_vocabulary(catalog, selection), cast_size(brief)))
    seed = brief["input"].get("seed")
    rng = random.Random(seed) if isinstance(seed, int) else random.Random()
    actions = next((group for group in groups if group["category"] == ACTIONS_CATEGORY), None)
    action_entries = list(dict.fromkeys(entry for pack in actions["packs"] for entry in pack["entries"])) if actions else []
    effective, profile = resolve_director_config(config, request)
    brief = {**brief, "_family": effective_model_family(request, profile, effective), "_avoid": avoid_patterns(brief),
             "_known": frozenset(known_labels(brief))}
    scenes, failed = {}, {}
    # Vocabulary search by meaning: a small separate embedding model, started only when a search needs it.
    embeddings = None if guided else embeddings_for(effective, progress)
    with closing(embeddings) if embeddings else nullcontext(), create_backend(effective).generation_session() as session:
        if action_entries:
            progress("Choosing the Actions & Poses entries that fit the request...")
            notes = {pack["name"]: pack["description"] for pack in actions["packs"] if pack.get("description")}
            action_entries = fitting_entries(session, brief, action_entries, checkpoint, progress, notes)
            groups = _only(groups, ACTIONS_CATEGORY, action_entries)
        # The place of every image comes from the place catalogs, not the writer (scene ideas bring their own).
        spaces = [] if guided else groups_of(catalog, SPACES, selection)
        places, setting = place_plan(brief, spaces, embeddings) if spaces else ([], "")
        if places:  # Spaces is dealt as places, never offered as suggestions or a list to pick from
            groups = [group for group in groups if group["category"] != SPACES]
        dealt, locked = deal_entries(action_entries, total, rng), locked_categories(brief)
        if dealt and levels(brief)["action"] == "locked":  # one pose for the whole set: the first dealt entry
            dealt = {number: dealt[1] for number in dealt}
        plan = {"entries": {_entry_key(entry): entry for entry in action_entries} or None,
                "cap": total if levels(brief)["action"] == "locked" else entry_cap(action_entries, total), "used": {},
                "dealt": dealt,
                "hands": deal_hands([group for group in groups if group["category"] not in locked], total, rng,
                                    words=requested_words(brief)),
                "props": [entry for group in groups if group["category"] != ACTIONS_CATEGORY
                          for pack in group["packs"] for entry in pack["entries"]]}
        if deals_frames(brief):  # dealt last, so runs without dealt frames deal exactly as before
            plan["frames"] = deal_frames(total, rng, required_frame(brief))
        if places:  # after everything else, so every other deal is seeded as before
            plan["places"] = deal_spread(places, total, rng, locked=levels(brief)["place"] == "locked")
            if dealt and levels(brief)["place"] != "locked":  # each dealt pose gets the dealt place that suits it best
                plan["places"] = pair(plan["places"], dealt, lambda pose, entries: fit_scores(pose, entries, embeddings))
            plan["setting"], plan["place_words"] = setting, telling_words(spaces)
        for start in range(0, total, BATCH):
            numbers = list(range(start + 1, min(total, start + BATCH) + 1))
            earlier = [_summary(scenes[number]) for number in sorted(scenes)][-EARLIER:]
            plan["vocabulary"] = vocabulary_prompt(_shuffled(groups, rng, VOCABULARY_SAMPLE))
            written, missing = _compose(session, brief, numbers, plan, inputs, earlier, checkpoint, progress, on_slot)
            scenes.update(written)
            failed.update(missing)
    missing = [{"slot": number, "stage": "scene", "input": inputs[number], **failed[number]} for number in sorted(failed)]
    records = [{"slot": number, "status": "failed" if number in failed else "written", "input": inputs[number],
                "concept": None, "stage": "scene" if number in failed else None,
                "reasons": list(failed[number]["reasons"]) if number in failed else [],
                "tries": failed[number]["tries"] if number in failed else 1}
               for number in range(1, total + 1)]
    return {"complete": not failed, "requested": total, "written": len(scenes), "missing": missing,
            "slots": records, "scenes": [scenes[number] for number in sorted(scenes)],
            "vocabulary": {"selection": selection_record(catalog, selection)}}
