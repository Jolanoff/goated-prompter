# Dataset architecture

Dataset produces prompts, not images. The rebuilt workflow uses
`features/dataset/v2/understanding.py`, the `scenes/` package and `prompts.py`:
Understanding → source-bound human confirmation → the scene writer (with any selected vocabulary) → final Builder prompts.
Scenes-only generation stops before Builder. This is the only Dataset workflow; the
earlier pipeline (ideas with scenes, per-scene actions, Continue, saved scene plans, durable
checkpoints, recent-idea history and the old private vocabulary file) has been retired.
Its files under `data/` are not read, changed or deleted; old fields in a saved Dataset draft
are dropped when the draft loads.

## Runs

Each requested image keeps its slot number through every stage. A run lives only in its job's result: each scene
is published as soon as it is written (stage `writing_scenes`), then each final prompt as it is written. Nothing is
saved to disk; the user copies, downloads or exports what to keep. Reload recovery, scene editing, per-image
regeneration and continuing a scenes-only run are not implemented.

Vocabulary (`features/vocabulary/catalog.py`): `vocabulary/core/scene_category_registry.json` is the source of
truth for the categories and their folders; `category_definitions.json` says what each means and
`prompt_instructions.json` what the scene writer is told about it. A pack is one JSON file in a registered folder,
exactly `{"name", "category", "entries": [texts]}`; its id is `<folder>/<file>`. Imported packs live in
`data/vocabulary/<folder>/<file>.json` with id `data/<folder>/<file>` (`POST /api/vocabulary/import` with
`{"filename", "content"}` checks one and saves it in its category's folder, replacing an earlier import of that file).
Each file is read on its own: one that cannot be read is reported with its reason and the others still load.
`GET /api/vocabulary/catalog` returns categories, packs and problems. Adding a category is one entry in each Core file
plus its folder. Packs carry no compatibility data. Instead of `entries` a pack may hold `groups`:
`[{"group", "words": [up to MAX_WORDS], "entries", "worlds"?, "shapes"?, "adult_default"?}]` (worlds from
`options.dataset.WORLDS`, every world when none; shapes from `options.dataset.SHAPES`, every image shape when none), each entry in one group only; the pack's entries are all its groups' entries. A built-in pack may be `"always": true`: it is
loaded for every run, selected or not (`always_on`). The always-on packs are the places of `vocabulary/Spaces/`
(Everyday-Places, Fantasy-Places, Outer-Space, Backdrops, Fun-and-Creative-Places: groups of 20 to 50, each group's
places fitting every one of its words), the looks of `vocabulary/Subjects/` (Female and Male, one group each,
named `female` and `male`) and the cameras of `vocabulary/Camera & Composition/Camera.json` (groups by the body
positions they show clearly).

Vocabulary engine (`features/vocabulary/`), shared by every category, Spaces first; each part has one job.
Understanding (the brief) says what a request asks for and allows; retrieval finds the entries a text names; selection
chooses the set; a category's owner only says which texts are searched and how its entries go with another
category's.
- `embeddings.py`: a small embedding model (`local_llama_cpp.embedding_model_path`, bge-small-en-v1.5) run by its own
  llama-server on the CPU (`backends/llama_cpp_process.py LlamaCppEmbedder`), apart from the generation model, started
  only when a search needs it and stopped when the scenes are written. Entry and group texts are embedded once and
  cached by their text in `data/cache/vocabulary-embeddings.json` (per model); a run's queries are embedded together.
  Without it, or when it fails, words still work.
- `retrieval.py`: `groups_of` indexes a category's selected packs, then its always-on packs (a plain pack's entries
  are each a group named by the entry). `match` returns the groups a text names, or none: exact words decide when they
  explain every content word of the text ("water" inside "water aquarium" does not count); a match that leaves words
  unexplained stays only when meaning also rates its group at least `MATCH_AGREE` ("sports hall" is not the
  corridor's "hall", "a cozy bedroom" is a bedroom); without exact words, the one group that stands out from all the others
  (`relevance` at least `MATCH_Z` and `MATCH_LEAD` above the next). Found groups keep only the entries the text points to: their name, or details the
  group's words do not explain, by meaning (`narrowed`, `NARROW_Z`: "a rainy street", "a white background"). A weak
  match is never forced. Entries made of parts (`entry_parts`: "copper red hair with blue eyes and fair skin" is hair,
  eyes and skin, each named by its last word) are searched part by part (`requested_parts`): what a text asks of a part
  fixes that part ("ginger": the hair, "green eyes": the eyes) and every other part stays free, word for word within
  one part ("dark skin" is "dark umber skin", not "dark brown eyes"), in any form of a word (`word_stem`: freckles,
  freckled), a word that starts with one a part says read as it ("redhead": red). What no part holds, contradicts a
  detail before it in the same part, or needs a part no entry has beside the fixed ones (a beard beside hair) is
  returned in the text's own words ("tall", "sleeve tattoos"). `fit_scores` says how
  well entries go with another category's entry; `telling_words` gives each entry the words that tell it apart.
- `selection.py`: `diverse_order` puts groups in an order where each next one is unlike those before it, `deal_spread`
  deals a set across them (no entry repeats before all have been dealt, a group whose entries are used up is passed
  over), `deal_composed` deals entries made of parts with the fixed parts dealt into them and every other part varying
  with the dealt entry, and `pair` moves dealt entries between images so each goes with the other category's entry on its image
  through the category's own fit (the same entries, only swapped).

Places (`v2/scenes/places.py`): when the place is free, or kept by the user's words, every image is dealt one place
the scene must use (`place_plan`, no model call). A named place is authoritative: the request's place words without
its setting ("in his room in space": "in his room", setting "in space") are matched among the groups of the request's
world, or of every world when a setting carries it; a place in no catalog uses its setting's group, then Understanding's ideas,
which for a named place are only that place or its kinds (words that were never a place, a time of day kept as one,
still find places; a place missing from the catalog still finds none); with nothing, nothing is dealt and the writer
follows the words. Place words that point to some of a group's places (a white background) stay that specific; a place named
broadly is widened by its ideas' groups that are close in meaning to the one it names
(`related`: closer than the other groups by `RELATED_Z`; nothing without embeddings). The setting goes to every image
with its place. No place named: the
user's selected Spaces packs when there are any; else the groups Understanding's ideas name (6 to 8 places, obvious and
less expected, over the kinds of place the request fits), each idea matched among the groups of the request's world,
with the `adult_default` groups first for an adult request. Retrieval adds no place on its own: what a request allows
is Understanding's judgement; an idea no group answers adds nothing. The groups go in `diverse_order`, the set is
dealt across them (a locked place is one for every image), and the dealt places are paired with the dealt Actions &
Poses entries (`pair` with `fit_scores`). Each image in IMAGES carries its `place` (and `setting`), the writer gets
`PLACE_RULE`, Spaces suggestions are dropped, and a scene whose space has none of its place's telling words is asked
again to build it there and keep its act (`place_problems`). With nothing found, or guided scenes, nothing is dealt
and the writer chooses as before. `python -m tests.eval.places` measures this on labelled cases
(`tests/eval/cases/places.json`, and `places_heldout.json`, never used to tune a setting), with Understanding's ideas
captured once by `python -m tests.eval.capture_ideas`.

Requested details (`v2/scenes/looks.py`): every character's `appearance` (Understanding: the request's own words about
how that person looks: an age, hair, eyes, skin, a beard, tattoos, a piercing) holds in every image, whatever the
vocabulary, known characters and guided scenes included. What no dealt look holds goes with every image as that
person's `details` (`requested_details`, `DETAILS_RULE`), and code adds a detail a scene leaves out (none of its words on
that person or in its extras) to the extras in the request's own words (`with_details`, after the copied-props check;
a writer asked again three times still left a beard out). A person gets nothing the request and their look do not
give (no scars, wounds or tattoos of the writer's own).

Looks (`v2/scenes/looks.py`): every human whose looks vary (`varied_labels`: not known, triggered, named or held by a
locked subject; not a custom character) is dealt a look in every image from the built-in looks (`look_groups`: the
always-on Subjects groups, `female` in `Subjects/Female` and `male` in `Subjects/Male`), with no model call
(`deal_looks`). A look is a hair style and colour, eyes and skin tone: a base that keeps the set's people apart. A
person's gender finds their group by the group's words (`exact_search`); a person of unspecified gender gets looks of
either. Their label and appearance fix only the parts of a look they name (`requested_parts`: "redhead", "brunette",
"freckles", "blue-eyed") and every other part varies (`deal_composed`): a ginger man with green eyes gets ginger hair
and green eyes in every image with different hairstyles, eye shapes and skin, where whole looks gave him one look
throughout. No look is dealt again before all have been, and the people of one image get different looks. Looks are
not searched by meaning: their words are too much alike for it ("a tall woman" ranks a blonde look first). Each image
in IMAGES carries its `looks` (`{label: look}`) and the writer gets `LOOK_RULE`: it keeps the look's colours and
hairstyle and describes the person as before; build follows the request or is chosen anew for every image, and a
character with no look (an animal) still varies. A scene whose person's skin, hair and eyes have none of the look's
telling words or the request's own words is asked again (`look_problems`, `look_words`). With the user's own Subjects
packs selected, or guided scenes, no look is dealt and the writer chooses as before.

Cameras (`v2/scenes/camera.py`): every image is dealt one whole camera from the built-in cameras (`camera_groups`: the
always-on Camera & Composition pack), with no model call of its own (`deal_cameras`). A camera is "<shot> with <angle>
and <view>" ("medium long shot with eye-level angle and three-quarter view"), written so its parts go together; its
group names the body positions it shows clearly and may list the image shapes it fits (`shapes`). Shot sizes are named
for any subject, people, animals, creatures, objects or places (`SHOT_SIZES`: extreme wide and wide shots keep the
surroundings, a full shot every subject whole, medium long and medium shots their main part, a close-up a face or one
detail; for a person they show full body, head to knees, head to hips and head and shoulders). Per image: only groups
that fit the aspect ratio's shape (`in_shape`; a lying body is never seen from the side at full length in a tall
image); only cameras inside the brief's `framing` (Understanding, `framed`): shots no nearer than `tightest`
(everyone and everything the request names, what they do and touch and where they are relative to each other stay in
view) and no farther than `widest` (what matters most, the act, interaction, arrangement or detail, still large enough
to read at this image shape for as many and as big subjects as there are), and views that see the subjects from the
side they face (`facing`, `VIEW_FACINGS`: a row posing for the viewer is never seen along the row); every shot also
shows every body part the request asks to show (`required_frame`) and, with a known character, at least head to hips.
When no camera fits, the widest bound opens first, then the facing; then the groups whose words the image's dealt pose (or the request's action) says (`exact_search`), else those
the request's words about the people say ("a team"), else the groups for any pose (not by meaning, like looks: the
groups are too much alike for it). A close-up stays when faces or one detail carry the request; a wide shot is dealt
when its arrangement needs the surroundings and a distant one never shrinks the act; nothing depends on the cast's
size. The request's camera words fix the
parts they name (`requested_parts`: "low angle", "side view", "close-up"), before the framing and facing, and every other part
varies; whole cameras that already hold the fixed parts come first (the suiting groups', else the any-pose ones', else
any group's), and only when none does is a part put into the dealt ones (`deal_composed`). A kept camera whose words
fix no part and name no body part ("from behind") is the request's own: none is dealt. Images that lead to the same
groups share one deal over those groups split by how much of a subject the shot shows (`deal_spread`), so a set
spreads over cameras and from far to close; a locked camera is one camera for every image. Each image in IMAGES
carries its `camera`, the writer gets `CAMERA_RULE` (keep the shot, height and side; what each shot size shows; keep
everyone and everything the request needs in view; the request's own camera words first) and no check asks a scene
again for it. A known character's dealt frame is the dealt shot's (`camera_frames`). With the user's own Camera &
Composition packs selected, or guided scenes, no camera is dealt and the packs stay suggestions as before.

Selection: the Dataset tab's Vocabulary Library selects packs by hand (search, category filter, preview,
Apply/Cancel); the selected ids are the draft's `vocabulary_packs`, saved with the other Dataset settings. They are
not part of the review signature, so changing them needs no new Understanding. Confirm checks them against the
catalog. Vocabulary is used only when scenes are invented (source `random`); with the user's own scene ideas
(`guided`) no vocabulary is sent and the selection is ignored.

Triggers (`v2/triggers.py`): the draft holds a list of up to 20 triggers, each `{text, kind, expand, start}`:
its type (character, style, outfit, object, other), whether code places its exact text (`off`), the model writes its
meaning (`on`) or both, and whether it goes first. Only the user knows what a token stands for, so nothing guesses it. A draft or brief from before the list reads its one trigger as an exact "other"
trigger.

Understanding (brief version 18) records everyone who appears (`characters`: each person, animal, creature, robot or
named character, even when the request is mostly about what they do or where they are; none for an object, product,
place or style on its own), and code derives the path from that list and the NSFW switch, so the model never judges
whether "characters are the point" (it listed no one for a man reading in a cafe, a chef or a cat; `python -m
tests.eval.understanding_cast` runs requests of every kind of cast). It also records the participant count, stated
attributes, the central activity, what stays fixed and what varies, each character's `appearance` (the request's own words about how that
person looks, kept only where the user wrote them), plus `places`: the user's words for what surrounds the place
(`setting`), the `world` of the surroundings and always 6 to 8 `ideas` of where it can happen (for a named place, only
that place or its kinds), and the `framing` every image's camera stays in: `tightest` and `widest` steps
(`options.dataset.FRAMINGS`: surroundings, whole, partial, close; the nearest that keeps everything the request needs
in view, the farthest at which what matters most still reads clearly in the image shape, which Understanding is given)
and `facing` (`FACINGS`: viewer, each other, one way, free); each "" when unknown, which leaves that side open. Each kept part has its own words: a time of day is light, the weather is mood, and every
act stays under action. The model fills the parts in `KEPT_ORDER` (who and what happens first), and code
drops words quoted for clothing or expression that are only the subject's or the action's, and any other part that
repeats them exactly (`_own_words`). It never reads
vocabulary. It links every character and outfit trigger (by
number) to exactly one person, the character's `triggers` (code checks it; a character trigger is one person, count 1),
and the review shows the link. Each character carries `known`: its looks come from its name or an
exact-text character trigger, so no step invents them. Version 9 to 15 briefs in saved runs stay readable.

Consistency (`v2/consistency.py`, options in `options/dataset.py`): what a dataset trains decides what stays the same.
Each part of the image (subject, clothing, action, expression, place, objects, camera, light, mood) is locked
(identical in every image), themed (every image follows the user's words for it, the rest of the part varies) or free
(new in every image). The draft's Dataset type gives defaults (`TYPE_CONSISTENCY`: a Pose / action set locks the
action, an Object / product set the objects, a Location set themes the place; Character themes the subject, which
keeps everyone the request names, triggers or knows and varies the rest). Understanding (brief version 15) quotes the
user's words per part and names the parts the request asks to be identical (`locked`) or to differ (`varied`); code
keeps only quoted words that are really in the request, and a lock only when those words ask for sameness
(`consistency.asks_same`: a named character, an object or "feet visible" stays themed). The brief stores the resolved `consistency` and the words
(`kept_words`): a part set by hand on the tab's Consistency row wins, then the request, then the type. Older briefs
read their kept parts as themed. Downstream: a locked action deals one Actions & Poses entry to every image; a locked
part's vocabulary category gets no per-image suggestion; frames are dealt to known characters only when the camera is
free; locked parts are copied from the first image (`same_as_image_1`) and never listed in `already_used`; a locked
subject holds only the people its words name, or everyone when they name nobody (`request.locked_people`), and the
others still vary. The quality tool counts repeats only for parts that are
not locked and reports `locked_drift`.

Scenes (`v2/scenes/`): the scene writer (`dataset_v2:scenes`, one call per batch of up to ten images) receives the
USER REQUEST, the EXISTING APPROVED REQUIREMENTS (rules, Understanding, style, and the capture when the style is Realistic) and, only when packs are selected, a
SELECTED VOCABULARY section: just the categories that have a selected pack, each with its Core instruction and the
entries of those packs (merged per category and shuffled for every batch by a generator seeded with the run's seed),
plus the shared vocabulary usage rules. A pack with a description (its author's note on what it is for and how its
entries are written) is listed under that note so it stays with its own entries. A note guides the choice of entries and never overrides the request or the settings. Each category sends a seeded sample of at most `VOCABULARY_SAMPLE` (40)
entries per batch, so a large pack never drowns the request. The request and the approved requirements always win. With an Actions & Poses
pack selected, the shared vocabulary engine keeps only the entries that fit the request and the cast, with no model
call (`v2/scenes/actions.py` `action_plan`): the entries made for the cast's number of people (`retrieval.for_cast`: a
pair gets entries for two, a group entries for a group, an entry for fewer people only when the packs have none for
the cast), without those that say what the request rules out (`retrieval.without_said`), and, when the request keeps
an action, only those that show it (`retrieval.match` with `entry_words`: a group's trigger words, then the entries
that say the action's own words in any form, then meaning). Only those are offered and dealt, spread over the packs'
groups (`deal_actions`), and with none the writer gets no Actions & Poses vocabulary and builds the act from the
request. An entry is a whole interaction with its people as letters, kept as written. Objects & Props
(`v2/scenes/props.py`): an object the request names is suggested to every image as in every other category
(`deal_hands`, below); otherwise every image is suggested one object from the groups that clearly suit its own dealt
pose and place (`suiting`, `SUIT_Z`: a group judged by its name and words, which say what its objects are for), none
when nothing does, so no action and object pair is ever listed and every image's pose, place, object and people make
one scene. Every scene names the entry it is built on (`entry`); code checks the entry is one of the fitting ones and that no
entry is used by more than two images (`ENTRY_CAP`, raised to the images-per-entry when fewer entries fit than images
are requested), and asks again otherwise. Every other selected category deals each image `HAND` (1) suggested
entries from a seeded deck, without repeats until the whole category has been dealt (`deal_hands`), so the
vocabulary spreads over the set. In a category with entries about something the request names (they share a word
with it that is rare in that category, `requested_entries`): when the request names only that thing, every image gets
only the entry it names (`named_entries`); when it also names the category or one of its packs (it asks for the kind in
general), every image gets one of those entries and one other; suggestions are optional: the writer uses the ones that fit the image, or none,
and never adds a subject or object only to use one. Only `always` packs are used without a selection (Places and Looks, above): character looks come from the request,
the approved requirements and the dealt looks, with vocabulary guidance only from manually selected Subjects packs. A known character has
only an expression in its scene; its look comes from its name, never from the writer or vocabulary. With known
characters each scene also has a frame per person; each image is dealt the frame its known characters get: its
dealt camera's shot (`camera_frames`), else `deal_frames` when the camera is free; a camera the request keeps in its
own words decides how much of everyone the image shows.
A scene holds only the people and their arrangement: subjects, actions, position, space, camera and extras. Each
position line places its person in the frame relative to the others and names the owner of every body part by
label, and says which body parts the camera can see; the final prompt describes a body part only when it is visible
(not turned away, hidden by another body or inside someone). Every person in the cast is a primary subject: the camera gives each a real presence whatever their role in
the action, shows as much of each body as the action needs (head to feet only when the pose needs it), keeps every
visible body part joined to its owner in the frame, and changes the arrangement or viewpoint rather than crop a
person out; background figures may be partly visible. The final prompt shows that framing through what is visible
(where each person is, which parts show, what lies in front and behind), not by a shot name. Every act needs the
bodies to reach each other (two acts at once only when a position reaches both partners, never a closed loop through
everyone), and positions and actions agree on who does what to whom. Every fact is written once: the actions own the
act, each position places one person around it without repeating it, the camera owns what is visible, and extras
hold only visible details, the clothing and the light source among them (a selected Clothing, Lighting or Mood & Tone
entry as visible things). An Actions & Poses entry is used as written and adapted only where it conflicts: the actions
copy its act line (who does what to whom, with the position's name, in everyday words) with only its people replaced,
and the final prompt keeps those words. Saved scenes
with the old clothing, lighting and mood fields still load (`retire_fields` drops them). Only a scene that would ruin
the image is asked again (wrong shape, an avoided phrase, an entry not in the vocabulary, a person the actions never
name, a known character without a visible face or cropped above the hips); repeating an earlier image, a kept part,
an entry or a dealt frame never is: variety comes from the prompt and the vocabulary's deal. Later batches
see earlier images field by field. Missing images are retried, then reported; the last round keeps an image rather
than lose it.

Prompts (`v2/prompts.py`): the existing Builder writes each final prompt from the decided scene (`decided_scene`):
it keeps the target adapter, length, style, templates and output format and leaves out its free-form layers
(analysis, priority, frame default, mode, creativity, preservation, Director). The run's Director shapes the scenes
instead, so its emphasis is decided once. The scene rules
ask Builder to keep every subject, action, object, place and camera, add none, write the scene's clothing and light
and choose only what it leaves open, and describe people rather than labels; known characters are named, never described. The Builder does not parse the scene as user rules
(`compile_rules=False`): the approved requirements already carry them. The Builder is told what exact-text triggers
carry (never describe it) and which meanings to write; an exact style trigger turns the Style and Capture settings off. Code places
every exact text itself (`place_triggers`): pinned ones first in list order, the rest by type in the Anima tag line,
at its person's first mention in prose, or in an Ideogram element's description, `style_description.aesthetics` or
`high_level_description`. The scene writer hears meaning triggers (`trigger_notes`). Final prompts use the run's Creativity setting.
Every prose target carries one rule for two or more people: a place in the frame per person, one short anchor
repeated at each mention, no shared pronouns, the owner, state and count of each body part that shows or touches,
and where the bodies touch and stay apart. Meaning triggers reach
the Builder as notes to rewrite: code asks once more when a prompt copies a note of three or more words or loses a
number it gives, and fails the image when the number is still missing (`meaning_problem`). Code rewrites once a
prompt that still uses a numbered label ("man 1") or its ordinal ("the first man"). The writer never sees those for a
person whose looks change: each is named by the least of their own look in that scene that tells everyone apart, in words without brackets
or commas ("the man with pale skin"; `anchors`, `name_people`); known,
triggered and named people keep their label. A scene whose actions do not name every person (an entry copied with
its placeholder people) is asked again (`unnamed_people`). At Creative and Dice, a role label ("servant", "ruler") is also replaced by the person's look, so the role is shown by
the scene's signs instead of named; quoted words stay. On Anima, code writes the tag line's people-count tags from
the cast, puts quality tags first and keeps one safety tag before the counts, writes tags with spaces (score tags
keep their underscores) and drops low-quality tags, score tags Anima does not know and invented solo tags
(`anima_tag_line`). Each scene shows the request through its own signs, specific enough to name without being told; the scene
writer writes them (extras) right after the pose, before the place and camera, and is asked to keep them, the place
and the camera new in every image. One set of library templates is picked for the whole run, so every
prompt has the same structure, and an entry's position name reaches the Builder only when the scene's actions say it
(an entry the writer had to swap or adapt would otherwise name a different act). Understanding drops a must or avoid
phrase that only repeats a trigger's text. Capture is Auto in the brief unless the style is Realistic. The Aspect ratio setting (Auto by default; `aspect.py`) reaches the scene writer and the Builder as one rule each, only when a ratio is chosen: poses, arrangement and framing are written for a tall, wide or square frame. Any style
trigger (any use) turns the Style off for every step (`run_style`), so not even Anima's anime default is added. The
Builder writes each scene with the run's Creativity, which alone decides how much is invented around the scene's
fixed people, placements, contact, action and camera, and is told that the
confirmed requirements win where a scene contradicts them. Those
requirements are the people, rules and must/avoid; the raw request and `fixed` are left out, since the scene already
carries them and the model would paste them in as content. An Actions & Poses entry decides how the requested activity
happens, never what it is: an entry showing a different act does not fit.

## Owners

| Concern | Owner |
| --- | --- |
| API admission: understand, confirm | `goated_prompter/features/dataset/routes.py` |
| Workflow execution (`dataset_understanding`, `dataset_v2_scenes`) | `goated_prompter/features/dataset/runner.py` (dispatched by `goated_prompter/workflow_runners.py`) |
| Editable draft defaults and validation | `goated_prompter/features/dataset/v2/draft.py`, saved by `goated_prompter/workflow_settings.py` |
| Understanding brief | `v2/understanding.py` |
| Adults-only and safety checks on the request | `v2/safety.py` |
| Source-bound, expiring, single-use approval tickets | `v2/tickets.py` |
| Guided input assignment | `v2/assignments.py` |
| Vocabulary categories, pack discovery and the vocabulary prompt section | `features/vocabulary/catalog.py` |
| Optional pack features (people count, slots) | `features/vocabulary/catalog.py`, `v2/scenes/entries.py` `fit_cast`, `features/vocabulary/retrieval.py` `for_cast`, `v2/scenes/slots.py` |
| Scene composition | `v2/scenes/` (`texts.py` instructions, `request.py` what the writer is asked, `entries.py` vocabulary offered and suggestions dealt, `actions.py` Actions & Poses, `props.py` Objects & Props, `places.py`, `looks.py`, `camera.py`, `checks.py` scene checks, `writer.py` batch and retries, `settings.py` limits; `write_scenes` in `__init__.py`) |
| Final prompts through the Builder | `v2/prompts.py` |

## Seeds

The draft's `seed` and `seed_mode` (randomize, fixed, increment) work like ComfyUI's seed
control. The frontend picks each new batch's seed and sends it with the reviewed request; the
seed is saved after Confirm starts the run, so a rejected or cancelled review changes nothing.
The seed is not part of the approval signature, so changing it invalidates nothing.
The seed decides only the run's random choices: the order and sample of vocabulary entries, which Actions & Poses
entry each image is dealt, which library templates are used and the model's sampling. The same seed with the same
settings repeats a run; it never changes what the request asks for.

## One job per setting

The request and rules decide the facts; NSFW whether the run is adult; triggers their exact text, meaning or both;
the Director what is emphasized; the target how the prompt is written; Length how long it is; Style the medium;
Creativity alone how much is invented around the facts (its guide text and the writers' temperature); vocabulary
which verified entries fit the request. The Builder and the scene writer both turn the request's abstract words (a
role, status, relationship, feeling or theme) into visible signs (`SHOW_DONT_TELL`, kinds of sign only, never
examples); Creativity decides how far the signs go, and only Creative and Dice may write the request's own words on
a prop, garment or body. The NSFW switch only allows adult content: the request decides whether an image shows an
act, a role, a display or a mood, and nothing adds nudity, acts or kinks the request does not call for. Later
batches also see earlier images' extras, so props and signs are not repeated. `tests/unit/shared/test_layer_independence.py` checks that no other guide
decides how much is invented.

## Evidence boundary

CPU tests use mocked models and synthetic temporary storage. They check data flow (selection, what reaches the
composer and Builder, failures), not real-model creativity, scene coherence or visual correctness. No browser
end-to-end test covers the Dataset tab. The general evaluation harness (`tests/eval/runner.py`) covers Builder and
MiniMax only.
