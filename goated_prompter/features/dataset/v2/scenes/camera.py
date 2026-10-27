"""Cameras: the shot size, camera height and side every image is seen from, chosen as one whole.

The built-in cameras are the always-on Camera & Composition pack (vocabulary/Camera & Composition/Camera.json): each
entry is a whole camera made of parts, "<shot> with <angle> and <view>" (retrieval.entry_parts), written so its parts
go together; its group's words are the body positions it shows clearly ("lying", "sitting") and its "shapes" the image
shapes it fits ("lying along the frame" fits square and wide images only; ASPECT_RULE). A group whose only word is its
name fits any pose or subject. Shot sizes are named for any subject, a person, an animal, a creature, objects or a
place (SHOT_SIZES: an extreme wide or wide shot keeps the surroundings, a full shot every subject whole, a medium long
or medium shot their main part, a close-up a face or one detail). Every image gets one camera, chosen in this order:
- The image shape (aspect.py): only the groups that fit it (retrieval.in_shape).
- How the request must be framed (framed): Understanding names a range for it (brief["framing"],
  options.dataset.FRAMINGS) and every shot stays inside: no nearer than "tightest", which keeps in view everyone and
  everything it names, what they do and touch and where they are relative to each other and to the things it names,
  and no farther than "widest", at which what matters most (the act, the interaction, the arrangement, the detail) is
  still large enough to read at this image shape, for as many and as big subjects as there are. Its "facing" (FACINGS)
  says which way the subjects face, and the view sees them from that side (VIEW_FACINGS: a row posing for the viewer
  is never seen along the row from its end). Every shot also shows every body part the request asks to show
  (entries.required_frame) and, with a known character, at least head to hips (settings.AT_LEAST_HIPS). So a close-up
  stays when faces or one detail carry the request, a wide shot is dealt when the arrangement needs the surroundings,
  and a distant one never shrinks the act; nothing depends on the cast's size or one kind of request. When no camera
  fits, the widest bound opens first, then the facing. The frame dealt to known characters is the dealt shot's
  (shot_frame).
- The body positions of the image: the groups whose words its dealt pose (or the request's action) says
  (retrieval.exact_search), else those the request's words about the people say ("a team"), else the groups for any
  pose. Cameras are not searched by meaning, like looks: the groups are too much alike for it ("cooking" ranked the
  sitting cameras first).
- The request's own camera words: what they ask of a part ("low angle", "side view", "close-up") fixes that part in
  every image (retrieval.requested_parts), before the framing range and the facing, and every other part varies. The whole cameras that
  already hold the fixed parts come first, so parts are never combined at random: those of the suiting groups, else
  of the groups for any pose, else of any group; only when none does is a fixed part put into the suiting cameras
  (selection.deal_composed). Words no part holds stay the request's own words, which the writer keeps first. A camera
  the request keeps whose words fix no part and name no body part to show ("from behind", "a selfie") is the
  request's own: no camera is dealt.
Images that lead to the same groups share one deal (selection.deal_spread over the groups split by how much of a
subject the shot shows), so a set spreads over their cameras and from far to close; a locked camera is one camera for every image. The writer arranges
everyone and everything the request needs inside the dealt camera (CAMERA_RULE). With the user's own Camera &
Composition packs selected, their entries are suggestions as before and no built-in camera is dealt. No model call
of its own, and no check asks a scene again for its camera.
"""

from .....options.dataset import FRAMINGS
from ....vocabulary.retrieval import entry_parts, exact_search, groups_of, in_shape, requested_parts, without_said
from ....vocabulary.selection import deal_composed, deal_spread
from ..aspect import aspect_shape, brief_aspect
from ..consistency import kept_words, levels
from .checks import named_frame
from .entries import required_frame
from .request import known_labels
from .settings import AT_LEAST_HIPS, SHOWS

CAMERA = "Camera & Composition"
# What each built-in shot size keeps in the frame (options.dataset.FRAMINGS, widest first) and, of a person, how much
# (settings.SHOWS). The names fit any subject (a person, an animal, a creature, objects, a place); a shot not listed
# here says nothing, so it is never ruled out.
SHOT_SIZES = {"extreme wide shot": ("surroundings", "full body"), "wide shot": ("surroundings", "full body"),
              "full shot": ("whole", "full body"), "medium long shot": ("partial", "head to knees"),
              "medium shot": ("partial", "head to hips"), "close-up shot": ("close", "head and shoulders")}
# The ways the subjects may face (options.dataset.FACINGS) for each built-in view to show them clearly: a front view
# sees subjects that face the viewer, a side view subjects turned to each other or all one way across the scene (it
# would look along a row posing for the viewer), a three-quarter view any of them; from above or a lying body's end,
# subjects that face up to the viewer or each other. "free" takes every view, and a view not listed is never ruled out.
VIEW_FACINGS = {"front view": {"viewer"}, "three-quarter view": {"viewer", "each other", "one way"},
                "side view": {"each other", "one way"}, "top-down view": {"viewer", "each other", "one way"},
                "end-on view": {"viewer", "each other"}}


def camera_groups(catalog):
    """The built-in cameras: the always-on Camera & Composition groups."""
    return groups_of(catalog, CAMERA, {"packs": []})


def shot_size(entry):
    """(framing, frame): what an entry's shot keeps in the frame and how much of a person it shows (SHOT_SIZES);
    (None, None) for a shot it does not list."""
    return SHOT_SIZES.get(" ".join(dict(entry_parts(entry)).get("shot", "").split()), (None, None))


def shot_frame(entry):
    """How much of every person an entry's shot shows (settings.SHOWS), or None."""
    return shot_size(entry)[1]


def _fits(entry, tightest, widest, facing, frames):
    """Whether an entry's camera frames the image as it needs: its shot inside the range (no nearer than tightest,
    no farther than widest, FRAMINGS), showing of a person no less than the frames allow (the widest index into
    SHOWS), and its view seeing the subjects from the side they face (VIEW_FACINGS). An empty bound is open."""
    step, frame = shot_size(entry)
    view = " ".join(dict(entry_parts(entry)).get("view", "").split())
    near = step is None or not tightest or FRAMINGS.index(step) <= FRAMINGS.index(tightest)
    far = step is None or not widest or FRAMINGS.index(step) >= FRAMINGS.index(widest)
    faces = facing in ("", "free") or view not in VIEW_FACINGS or facing in VIEW_FACINGS[view]
    return near and far and faces and (frame is None or SHOWS.index(frame) <= frames)


def _kept(groups, keep):
    """The groups with only the entries keep accepts; a group left with none is left out."""
    kept = [{**group, "entries": [entry for entry in group["entries"] if keep(entry)]} for group in groups]
    return [group for group in kept if group["entries"]]


def _holds(fixed):
    """Whether an entry already has, for every fixed facet, one of the parts fixed for it."""
    return lambda entry: all(dict(entry_parts(entry)).get(facet) in parts for facet, parts in fixed.items())


def _by_shot(groups):
    """Every group split by how much of a subject its entries' shots show (the wide and full shots alike show it
    whole), so a set dealt from them spreads over close and far as well, the full shots sharing one turn."""
    split = {}
    for group in groups:
        for entry in group["entries"]:
            shows = shot_frame(entry) or dict(entry_parts(entry)).get("shot")
            split.setdefault((id(group), shows), {**group, "entries": []})["entries"].append(entry)
    return list(split.values())


def _general(groups):
    """The groups for any pose: those with no words of their own (their only word is their name)."""
    return [group for group in groups if len(group["words"]) <= 1]


def suiting(groups, act, people=""):
    """The groups for the body positions the image shows: those whose words its act says, else those whose words the
    words about its people say ("a team": a group), else the groups for any pose, else all of them. The act comes
    first: "two friends hugging" are hugging, not a group lined up."""
    specific = [group for group in groups if len(group["words"]) > 1]
    return exact_search(specific, act) or exact_search(specific, people) or _general(groups) or groups


def camera_limits(brief):
    """(image shape or None, the brief's framing {"tightest", "widest", "facing"}, the widest index into SHOWS a dealt
    shot may be): the range and facing Understanding names for the request (everything it needs in view, what matters
    most still clear at this image shape, the subjects seen from the side they face), every body part the request asks
    to show, and known characters at least head to hips."""
    found = aspect_shape(brief_aspect(brief))
    needed = required_frame(brief)
    frames = SHOWS.index(needed) if needed in SHOWS else len(SHOWS) - 1
    if known_labels(brief):
        frames = min(frames, len(AT_LEAST_HIPS) - 1)
    framing = brief.get("framing") if isinstance(brief.get("framing"), dict) else {}
    return ((found[0] if found else None),
            {key: framing.get(key) or "" for key in ("tightest", "widest", "facing")}, frames)


def framed(groups, framing, frames, fixed):
    """The groups with only the cameras that frame the image as it needs (_fits). The request's own camera words come
    first: a shot or view they fix opens that side. When no camera fits, the widest bound opens first, then the
    facing: everything the request needs stays in view."""
    tightest, widest, facing = ("", "", framing["facing"]) if "shot" in fixed else (
        framing["tightest"], framing["widest"], framing["facing"])
    facing = "" if "view" in fixed else facing
    for bounds in ((tightest, widest, facing), (tightest, "", facing), (tightest, "", "")):
        if found := _kept(groups, lambda entry: _fits(entry, *bounds, frames)):
            return found
    return []


def deal_cameras(brief, groups, total, rng, poses=None):
    """{slot: camera} for every image (see the module docstring); {} when no built-in camera fits. poses: {slot: the
    Actions & Poses entry dealt to that image}."""
    shape, framing, frames = camera_limits(brief)
    fitting = in_shape(without_said(groups, brief.get("avoid") or ()), shape)
    words = kept_words(brief)
    # What the request's own camera words ask of a part holds, a shot size or a view too: they come before the framing.
    fixed, _ = requested_parts(fitting, words.get("camera", ""))
    visible = framed(fitting, framing, frames, fixed)
    if not visible:
        return {}
    if levels(brief)["camera"] != "free" and words.get("camera") and not fixed and not named_frame([words["camera"]]):
        return {}  # the request's own camera ("from behind", "a selfie") fixes no part: it decides the camera
    locked = levels(brief)["camera"] == "locked"
    pools = {}
    for number in range(1, 2 if locked else total + 1):
        suits = suiting(visible, (poses or {}).get(number) or words.get("action", ""), words.get("subject", ""))
        holds = _holds(fixed)
        pool = _kept(suits, holds) or _kept(_general(visible), holds) or _kept(visible, holds) or suits
        pools.setdefault(tuple(map(id, suits)), (pool, pool is suits and bool(fixed), []))[2].append(number)
    dealt = {}
    for pool, composed, numbers in pools.values():
        order = _by_shot(pool)
        rng.shuffle(order)  # every seed starts the set at a different group
        cards = deal_composed(order, fixed, len(numbers), rng) if composed else deal_spread(order, len(numbers), rng)
        dealt.update({number: cards[index] for index, number in enumerate(numbers, 1)})
    return {number: dealt[1] for number in range(1, total + 1)} if locked else dealt


def camera_frames(dealt):
    """{slot: frame} for the known characters of every image, from its dealt camera's shot; {} when a shot names none."""
    frames = {number: shot_frame(camera) for number, camera in dealt.items()}
    return frames if frames and all(frames.values()) else {}
