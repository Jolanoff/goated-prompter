"""Vocabulary policies: what each vocabulary category does in a Dataset run (POLICIES), and the one engine that plans
the vocabulary of every image before the scene writer runs (plan_vocabulary).

A policy says when its category takes part in a run at all (applies_when), whether its built-in always-on packs are
used for this request (always_available, auto_when), whether the scene needs that part even without vocabulary
(required_when), which Understanding parts it follows (understanding_fields), whether the user's selected packs of it
are dealt by the category itself or suggested (selected_packs), how its entries are assigned and what the scene gets
when nothing is dealt (fallback): "writer" (the writer writes that part from the request, as before vocabulary) or
"none" (the part is left out).

The engine owns the common steps, so no category repeats them: eligibility, the request's locked parts, the selected
packs before the built-in ones, retrieval (retrieval.groups_of), the selected packs no category deals itself (dealt to
every image as suggestions, entries.deal_hands, with the things the request names "needed" in every image) and the
fallback. A category's own functions only do what is its own: its compatibility filters (find) and its dealing (deal).

Order: retrieval runs for every policy in registry order, then dealing: the actions first, the suggestions and the
known characters' frames, then every other policy in registry order. Every random call happens where it always has,
so a seed gives the same images. No model call.
"""

from dataclasses import dataclass
from typing import Callable

from ....vocabulary.retrieval import fit_scores, groups_of, telling_words
from ....vocabulary.selection import deal_spread, pair
from ..consistency import kept_words, levels, locked_categories
from .actions import act_plans, action_plan, deal_actions, deal_assignments, suited_to_place, with_roles
from .camera import CAMERA, camera_frames, deal_cameras
from .entries import (_only, deal_frames, deal_hands, entry_cap, kept_things, offered, required_frame,
                      requested_words, _entry_key)
from .looks import SUBJECTS, deal_looks, look_words, requested_details
from .places import SPACES, arrangement, place_plan
from .props import OBJECTS, deal_props
from .request import deals_frames
from .settings import ACTIONS_CATEGORY

CLOTHING, EXPRESSIONS, LIGHTING, MOOD, EFFECTS = (
    "Clothing", "Expressions", "Lighting", "Mood & Tone", "Effects & Atmosphere")


@dataclass(frozen=True)
class VocabularyPolicy:
    category: str
    always_available: bool = False  # its built-in always-on packs take part without being selected
    applies_when: Callable[[dict], bool] = lambda run: True  # the category takes part in this run at all
    auto_when: Callable[[dict], bool] = lambda run: True  # its built-in packs are used for this request
    required_when: Callable[[dict], bool] = lambda run: False  # the scene needs this part, vocabulary or not
    understanding_fields: tuple[str, ...] = ()  # the Understanding parts (kept words, consistency) it follows
    selected_packs: str = "suggested"  # the user's packs of it: "dealt" by the category itself, or "suggested"
    assignment: str = "per_image"  # "per_image", "per_subject" or "per_interaction"
    fallback: str = "none"  # what the scene gets when nothing is dealt: "writer" or "none"
    needed_words: Callable[[dict], frozenset] | None = None  # the request's words that name entries needed everywhere
    find: Callable[[dict, list], list] | None = None  # its compatibility filters: (run, retrieved groups) -> found
    deal: Callable[[dict, list], bool] | None = None  # its seeded dealing into run["plan"]: (run, found) -> dealt any


def locked(category, run):
    """Whether the request locks a part the category's policy follows (one version of it in every image)."""
    return any(run["levels"].get(part) == "locked" for part in POLICY[category].understanding_fields)


def _entries_text(assigned):
    """{slot: the entries of an image's acts as one text} for what reads the dealt pose as words (pairing a place,
    suiting an object); images without any entry are left out."""
    return {number: text for number, items in assigned.items()
            if (text := "; ".join(item["entry"] for item in items if item["entry"]))}


def _settle_acts(run):
    """The composed acts are final: the writer is offered only the entries its images were dealt (one dropped for the
    place would otherwise still be listed and used)."""
    run["plan"]["composed"] = run["assigned"]
    run["groups"] = _only(run["groups"], ACTIONS_CATEGORY, [item["entry"] for items in run["assigned"].values()
                                                           for item in items if item["entry"]])


# Actions & Poses (actions.py): the selected packs' entries made for the cast that show the act, one plan per act for
# separate acts (act_plans), each act kept with its own people and roles; with none, the writer builds the act.
def _find_actions(run, rows):
    found = offered(rows, ACTIONS_CATEGORY, run["groups"])
    run["plans"] = act_plans(run["brief"], found, run["embeddings"])
    poses = action_plan(run["brief"], found, run["embeddings"]) if run["plans"] is None else [
        group for _, plan in run["plans"] for group in plan]
    run["groups"] = _only(run["groups"], ACTIONS_CATEGORY, [entry for group in poses for entry in group["entries"]])
    return poses


def _deal_actions(run, poses):
    entries, total = [entry for group in poses for entry in group["entries"]], run["total"]
    held = locked(ACTIONS_CATEGORY, run)
    run["assigned"] = (with_roles(deal_assignments(run["plans"], total, run["rng"], held))
                       if run["plans"] and poses else None)
    run["dealt"] = (_entries_text(run["assigned"]) if run["assigned"] is not None
                    else deal_actions(poses, total, run["rng"], held) if poses else {})
    run["plan"].update({"entries": {_entry_key(entry): entry for entry in entries} or None,
                        "cap": total if held else entry_cap(entries, total), "used": {},
                        "dealt": {} if run["assigned"] is not None else run["dealt"]})
    if run["assigned"] is not None:
        _settle_acts(run)
    return bool(run["dealt"])


# Spaces (places.py): every image's place, from the places the request names, else the compatible ones; each paired
# with its image's dealt pose. Spaces dealt as places are never offered as suggestions or a list to pick from.
def _find_places(run, rows):
    places, run["setting"] = place_plan(run["brief"], rows, run["embeddings"]) if rows else ([], "")
    run["spaces"] = rows
    if places:
        run["groups"] = [group for group in run["groups"] if group["category"] != SPACES]
    return places


def _deal_places(run, places):
    if not places:
        return False
    plan, held = run["plan"], locked(SPACES, run)
    plan["places"] = deal_spread(places, run["total"], run["rng"], locked=held)
    if run["dealt"] and not held:  # each dealt pose gets the dealt place that suits it best
        plan["places"] = pair(plan["places"], run["dealt"],
                              lambda pose, entries: fit_scores(pose, entries, run["embeddings"]))
    if run["assigned"] is not None:  # an entry its image's place does not suit is dropped there, never its act
        run["assigned"] = suited_to_place(run["assigned"], plan["places"],
                                          [entry for group in places for entry in group["entries"]], run["embeddings"])
        run["dealt"] = _entries_text(run["assigned"])
        _settle_acts(run)
    plan["setting"], plan["place_words"] = run["setting"], telling_words(run["spaces"])
    return True


# Objects & Props (props.py): the things the request keeps are needed in every image (the suggestions step); otherwise
# an optional object from the selected packs that suits each image's own pose and place, none when nothing does.
def _find_objects(run, rows):
    return [] if locked(OBJECTS, run) else offered(rows, OBJECTS, run["groups"])


def _deal_objects(run, objects):
    plan = run["plan"]
    if not objects or plan["needed"]:
        return bool(plan["needed"])
    act = kept_words(run["brief"]).get("action", "")
    scene_of = {number: " ".join(filter(None, (run["dealt"].get(number), act, (plan.get("places") or {}).get(number))))
                for number in range(1, run["total"] + 1)}
    partners = {number: text for number, text in scene_of.items() if text}
    props = deal_props(objects, run["total"], run["rng"], partners, run["embeddings"])
    for number, prop in props.items():
        plan["hands"].setdefault(number, {})[OBJECTS] = [prop]
    return bool(props)


# Subjects (looks.py): a look for every human whose looks vary, from the built-in looks; what the request says each
# person looks like holds in every image, looks or not.
def _deal_looks(run, looks):
    plan = run["plan"]
    if looks and (dealt := deal_looks(run["brief"], looks, run["total"], run["rng"], run["embeddings"])):
        plan["looks"], plan["look_words"] = dealt, look_words(looks, run["brief"], dealt)
    plan["details"] = requested_details(run["brief"], looks, run["embeddings"])
    return "looks" in plan


# Camera & Composition (camera.py): one whole camera per image for its pose, the image shape and what must show; a
# known character's frame is the dealt shot's.
def _deal_cameras(run, cameras):
    posed = ({number: [item["entry"] or item["act"] for item in items] for number, items in run["assigned"].items()}
             if run["assigned"] is not None else run["dealt"])  # every act of a composed image: one camera for all
    if not cameras or not (dealt := deal_cameras(run["brief"], cameras, run["total"], run["rng"], posed)):
        return False
    run["plan"]["cameras"] = dealt
    if run["brief"]["_known"] and (frames := camera_frames(dealt)):
        run["plan"]["frames"] = frames  # the known characters' frame is the dealt shot's
    return True


def _without_own(category):
    """The built-in packs are used unless the user's own packs of the category are in the run (they stay suggestions)."""
    return lambda run: not run["guided"] and not any(group["category"] == category for group in run["groups"])


_people = lambda run: bool(run["brief"]["characters"])
_not_guided = lambda run: not run["guided"]

ACTIONS = VocabularyPolicy(ACTIONS_CATEGORY, required_when=_people, understanding_fields=("action",),
                           selected_packs="dealt", assignment="per_interaction", fallback="writer",
                           find=_find_actions, deal=_deal_actions)
POLICIES = (
    ACTIONS,
    VocabularyPolicy(SPACES, always_available=True, applies_when=_not_guided, required_when=lambda run: True,
                     understanding_fields=("place",), selected_packs="dealt", fallback="writer",
                     find=_find_places, deal=_deal_places),
    VocabularyPolicy(OBJECTS, required_when=lambda run: bool(kept_things(run["brief"])),
                     understanding_fields=("objects",), selected_packs="dealt", fallback="writer",
                     needed_words=lambda run: kept_things(run["brief"]), find=_find_objects, deal=_deal_objects),
    VocabularyPolicy(SUBJECTS, always_available=True, auto_when=_without_own(SUBJECTS), required_when=_people,
                     understanding_fields=("subject",), assignment="per_subject", fallback="writer", deal=_deal_looks),
    VocabularyPolicy(CAMERA, always_available=True, auto_when=_without_own(CAMERA), required_when=lambda run: True,
                     understanding_fields=("camera",), fallback="writer", deal=_deal_cameras),
    VocabularyPolicy(CLOTHING, required_when=_people, understanding_fields=("clothing",), fallback="writer"),
    VocabularyPolicy(EXPRESSIONS, required_when=_people, understanding_fields=("expression",), fallback="writer"),
    VocabularyPolicy(LIGHTING, required_when=lambda run: True, understanding_fields=("light",), fallback="writer"),
    VocabularyPolicy(MOOD, understanding_fields=("mood",)),
    VocabularyPolicy(EFFECTS, understanding_fields=("mood",)),
)
POLICY = {policy.category: policy for policy in POLICIES}


def retrieve(policy, run):
    """A category's groups (retrieval.groups_of): the user's selected packs first when the category deals them itself,
    with its always-on packs; only the built-in always-on packs when its selected packs stay suggestions and the
    request uses its built-in ones (auto_when); none otherwise."""
    if policy.selected_packs == "dealt":
        return groups_of(run["catalog"], policy.category, run["selection"])
    if policy.always_available and policy.auto_when(run):
        return groups_of(run["catalog"], policy.category, {"packs": []})
    return []


def _suggest(run, found):
    """The selected packs no category deals itself, one suggestion per category for every image (entries.deal_hands),
    except the categories of locked parts; the entries the request names are needed in every image instead. The
    suggestions and the copy check (props) read the groups retrieval left (offered), as they always have."""
    brief, plan, held, left = run["brief"], run["plan"], locked_categories(run["brief"]), run["offered"]
    owned = {policy.category for policy in POLICIES if policy.selected_packs == "dealt" and found[policy.category]}
    named = {policy.category: policy.needed_words(run) for policy in POLICIES if policy.needed_words}
    plan["hands"] = deal_hands([group for group in left if group["category"] not in held], run["total"],
                               run["rng"], words=requested_words(brief), owned=owned, own_words=named)
    plan["props"] = [entry for group in left if group["category"] != ACTIONS_CATEGORY
                     for pack in group["packs"] for entry in pack["entries"]]
    plan["needed"] = {number: {category: hand.pop(category) for category in named if category in hand}
                      for number, hand in plan["hands"].items() if set(named) & set(hand)}


def plan_vocabulary(brief, catalog, selection, groups, embeddings, rng, guided):
    """(plan, groups, outcome): every image's dealt vocabulary for the scene writer (plan), the selected vocabulary the
    writer is offered as a list (groups) and what each category gave: "dealt", "suggested", its fallback when the
    scene needs it, else "none"."""
    run = {"brief": brief, "catalog": catalog, "selection": selection, "groups": groups, "embeddings": embeddings,
           "rng": rng, "guided": guided, "total": brief["input"]["amount"], "levels": levels(brief),
           "plans": None, "assigned": None, "dealt": {}, "spaces": [], "setting": "",
           # The request's spatial relations go with every image, places dealt or not (scene ideas keep their own).
           "plan": {"arrangement": [] if guided else arrangement(brief)}}
    applies = {policy.category: policy.applies_when(run) for policy in POLICIES}
    found = {}
    for policy in POLICIES:  # retrieval and compatibility filters: no random call
        rows = retrieve(policy, run) if applies[policy.category] else []
        found[policy.category] = policy.find(run, rows) if policy.find and applies[policy.category] else rows
    run["offered"] = run["groups"]  # what retrieval leaves for the suggestions, before any act is settled
    dealt = {ACTIONS.category: ACTIONS.deal(run, found[ACTIONS.category])}
    _suggest(run, found)
    if deals_frames(brief):
        run["plan"]["frames"] = deal_frames(run["total"], run["rng"], required_frame(brief))
    for policy in POLICIES[1:]:
        if policy.deal and applies[policy.category]:
            dealt[policy.category] = policy.deal(run, found[policy.category])
    suggested = {category for hand in run["plan"]["hands"].values() for category in hand}
    outcome = {policy.category: "dealt" if dealt.get(policy.category)
               else "suggested" if policy.category in suggested
               else policy.fallback if applies[policy.category] and policy.required_when(run) else "none"
               for policy in POLICIES}
    return run["plan"], run["groups"], outcome
