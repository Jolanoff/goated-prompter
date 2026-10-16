# Vocabulary specification, version 1

Vocabulary packs declare reusable bodies, postures, positions, actions, objects, spaces and visual
directions. Core combines their optional components into scenes, checking compatibility during
selection. The Director steers selection and presentation; a lightweight Scene Builder fills open
details, and the target controls final prompt wording. User requirements take precedence. A pack
never decides whether a request is NSFW and never contains code. Unsupported images use the clearly
labelled freeform path. Core remains available without installed packs.

Files:

| File | Contract |
|---|---|
| `manifest.schema.json` | `manifest.json` of every pack |
| `entry.schema.json` | every entry file (`{"spec": 1, "entries": [...]}`) and every entry |

Locations:

| Folder | Packs | Can be |
|---|---|---|
| `vocabulary/core/` | internal interfaces and capability definitions, loaded through `foundation.json` | always loaded; no selectable content |
| `vocabulary/packs/<pack-id>/` | official content packs (`general`, `fantasy`, `adult`, `visual`) | enabled by default; disabled and re-enabled; read-only |
| `data/vocabulary/packs/<pack-id>/` (Git-ignored) | packs the user installed | enabled by default; disabled, updated and removed |

Official and installed packs are found automatically; nothing is copied. `data/vocabulary/state.json`
keeps which official and installed packs are disabled. A pack id may appear in one location only: a
duplicate is rejected, never silently overridden, and an archive cannot install over a core or official pack.
Additional content is a separate pack the user installs, never a hardcoded engine switch.

Per-run selection. A Dataset run chooses its own packs; the enabled state above is only the default the
Dataset tab starts from, and choosing packs for a run never changes it. On Confirm, before any inference,
the chosen pack ids are resolved (`PackManager.resolve_selection`) into the core, the selected packs and
every pack they require, directly or not (each marked `core`, `selected` or `dependency`), whatever their
global enabled state. An unknown, invalid or dependency-blocked choice is refused with every problem named.
The run records the result with each pack's version and content fingerprint: SHA-256 over `manifest.json`
and the entry files it lists, by name, so an edit without a version change is still a different
fingerprint. Only the recorded packs take part in that run's retrieval, scoring, activation, categories and
links; isolation and every rule below apply within them. Against a recorded selection
(`PackManager.selection_drift`), a pack that is missing, invalid, at another version, changed at the same
version, or now requiring a pack outside the selection is drift: the run, or an inspection of it, is refused
with the differences, never served by another version or the global selection. A pack disabled globally
since is not drift: the run keeps it. Runs saved before selections were recorded show theirs as not
recorded; nothing is inferred from current settings.

## 1. Packs

A pack is a folder with `manifest.json` and the entry files it lists. `id` is the pack's
namespace. `requires` maps pack ids to version ranges (`>=1.0.0 <2.0.0`). `categories` declares
the groupings the pack introduces; any loaded pack may use a category declared by itself or by a
pack it requires. Categories only group entries for retrieval and the UI: **the engine never
branches on a category**. Behaviour comes only from an entry's typed components. The words of a
category's name and description are how a broad brief opens it for inspiration (section 10), so write
them in the words briefs use. A pack's theme is its `name` plus the optional `themes`: words and phrases a
brief uses to ask for the pack as a whole ("BDSM", "bondage play"), each matched as an ordered phrase and
needing a word that is not a rating. A pack's `description` is informational and never reaches anything.
A specific concept of a pack belongs on its entries (names, aliases, tags), not in `themes`.

Migration: before `themes` existed, a word only a pack's description used reached its theme.
It no longer does; a pack that relied on one ("Cyberpunk: neon cities") declares it in `themes`. The
pack's name still reaches its theme without any declaration.

`activation` says when a pack's entries may be offered as ideas the brief did not name (section 10).
`"theme"`, the default, offers them only to briefs that reach the pack's theme. `"content"` also offers
them when an NSFW brief's content level equals an entry's rating, for a pack of general content at its
level (the bundled Adult pack); a General-rated pack cannot declare it. Opt-in or specialised packs
(kinks) keep the default, so the content level alone never offers them. The rating still decides what is
allowed, and an entry the brief names is found whatever its pack's activation. `"always"` offers a
pack's general-purpose ideas without a theme match, but only within the selected packs and allowed
ratings. General uses this mode; disabling or deselecting it removes its content, not Core interfaces.

## 2. Entries

Every entry has a header (`id`, `category`, `name`, optional `description`, `aliases`, `tags`,
`rating`, `extends`, `notes`, `abstract`, `replaces`) and a `components` object. Every component
is optional: `components: {}` is valid. Unknown fields and undeclared component types are rejected.

- `id` is `pack:local.name`, unique across all loaded packs, and its prefix is the pack's id.
- References to other entries use the full id (`core:limb.hand`).
- `notes` is plain text for the director. The resolver never reads it; no behaviour can live there.
- Components are typed and optional. An entry uses only the components it needs:

| Component | Meaning |
|---|---|
| `capability` | this entry is a capability; `implies` lists broader capabilities |
| `body` | resource instances (`hand.left`), extra capabilities, and capabilities declared complete |
| `participants` | the slots of a posture, position or action (single or group) |
| `requirements` | eligibility: capabilities each participant, object or the space must have; access needed |
| `spatial` | feasibility: posture, facing, anchors and access between participants |
| `claims` | resources a participant uses (support, holding, contact), exclusive or shared |
| `object` | what an item provides, how many hands it takes, and capabilities it declares complete |
| `environment` | the surfaces and supports a space provides |
| `visual` | framing, camera angle, composition, lighting or atmosphere; optionally what it can show |
| `visibility` | what this entry requires in view: participants, body regions, contact and place |
| `capacity` | independently reusable occupancy limit (`beings`), also accepted inside object/environment |

A capability is provided by a body through the types of its resource instances, its `provides`
list, and everything those capabilities imply (transitively).

### Core interfaces and pack inheritance

`core/foundation.json` declares the 17 public interfaces below. These are executable contracts, not
entry names: `ComponentTypes` validates interface payloads against `entry.schema.json`, resolves
pack-defined types through their dependency closure, and normalizes them to the existing runtime
components before inheritance and reference checking. The canonical lower-case components remain
valid too. No interface is mandatory on an entry; absence supplies no evidence of compatibility.

| Interface | Canonical contract | Runtime behavior |
|---|---|---|
| Actor | `participants` | being/object bindings, exact/range counts, group topology, duplicate-binding checks |
| Anatomy | `body` | resource instances, provided/implied capabilities and explicit completeness |
| Object | `object` | provided capabilities, completeness, object eligibility and optional capacity |
| Space | `environment` | surface/support capabilities, completeness and optional capacity |
| PostureBase | `spatial` | reusable self placement; referenced postures retain requirements, claims and visibility |
| PositionBase | `spatial` | participant placements, orientation, facing, access and placement conflicts |
| ActionBase | `requirements` | participant/space eligibility and required touch/sight access; compose with Actor and claims |
| RelationshipBase | `spatial` | relative anchors/facing and contradictory relationship checks |
| Framing | `visual`, dimension `framing` | crop/region visibility fitting, media/cast limits and conflicts |
| CameraAngle | `visual`, dimension `camera_angle` | camera selection, media/cast limits and conflicts |
| Composition | `visual`, dimension `composition` | layout selection, media/cast limits and conflicts |
| LightingBase | `visual`, dimension `lighting` | lighting selection, media/cast limits and conflicts |
| CapabilityCompatibility | `requirements` | all/any/none conditions against transitive `capability.implies`, unknown versus declared absence |
| BodyResourceUsage | `claims` | exclusive/shared allocation, shared keys and over-allocation checks |
| VisibilityRequirements | `visibility` | bound participant/region/contact/place needs collected for visual fitting |
| SupportSurfaceRequirements | `requirements` | required surfaces on the space or bound objects; missing/undeclared support checks |
| OccupancyCapacity | `capacity` | cast occupancy and beings on/astride objects; absent limits are not invented |

MODPACKs can declare a reusable type in their manifest:

```json
"component_types": {"my_pack:grip": {"base": "BodyResourceUsage"}}
```

An entry can then use `"components": {"my_pack:grip": {"actor": [...]}}`. Another pack requiring
`my_pack` can derive another named type from `my_pack:grip` and inherit its entries. Names must use
the declaring pack's namespace. Unknown bases, cycles, undeclared dependency access and incompatible
visual dimensions are rejected. Combining interfaces that share a canonical component merges their
constraints with the same contradiction checks as entry inheritance. Extensions reuse known mechanics;
they cannot introduce executable code or silently add unsupported fields.

Core contains no body plans, poses, actions, objects, environments or visual presets, even marked
abstract. Human, Humanoid, Quadruped and anatomical traits belong to General; Fantasy and Adult
require General only where they reference its content. Concrete visual directions and everyday
interactions also belong to General. General's abstract object-interaction templates are pack content,
not Core interfaces. Packs needing none of that content can require Core alone.
Packs written against the former `core:body.*`, `core:trait.*` or scene-content ids must use their
`general:` ids and declare the General dependency. No content is copied back into Core to satisfy them.

## 3. Status and precedence

The resolver (Phase 3) reports one status per composition (entries bound to a cast). It never
claims physical possibility; it reports what the declared data supports.

| Status | Meaning |
|---|---|
| `conflict` | A declared rule is broken. The only status that rejects. |
| `unknown` | Some requirement cannot be evaluated because the data does not say. |
| `eligible` | Every requirement is satisfied, but placement or access is not fully declared. |
| `feasible` | Every requirement is satisfied and every participant's placement and every required access is covered by declared spatial facts. "Declared feasible", not proven. |

**Precedence:** `conflict` > `unknown` > `eligible` > `feasible`. A composition takes the highest
status any of its checks produces.

**Undeclared versus explicitly missing.** A body is *complete* for a capability when that
capability, or one it implies, is listed in the body's `complete_for` (or in the cast member's
`complete_for` at composition time). Then any capability under it that the body does not provide is
**absent**. Otherwise a capability the body does not provide is **undeclared**.

Objects follow the same rule. An item's `object.complete_for` (or the composition object's
`complete_for`) makes every capability under it that the item does not `provides` **absent**;
anything else the item does not provide is **undeclared**. A plain rod that provides
`core:item.handheld` and is complete for `fantasy:magic` lacks `fantasy:magic.focus` (a `conflict`
where a focus is required); an item that never mentions magic leaves it undeclared (`unknown`).
Completeness never hides what is provided.

**Undescribed participants.** A cast member with `"body": null`, or an object with `"item": null`,
is valid. It is not described, so any `complete_for` given for it is ignored: every capability is
undeclared, and every check on it gives `unknown`, never `conflict`. The finding names the
participant and the capability that is undeclared.

| Requirement | provided | absent (complete) | undeclared |
|---|---|---|---|
| `all_of: X` | satisfied | `conflict` | `unknown` |
| `any_of: [X, Y]` | satisfied if any is provided | `conflict` if all are absent | `unknown` otherwise |
| `none_of: X` | `conflict` | satisfied | `unknown` |

Other `conflict` sources: a resource claimed beyond its available instances, an access to a
region whose resource is claimed exclusively as support (sitting on it, lying on it), a slot bound
with fewer or more members than its `count` (including a required slot left unfilled), a declared
access whose `from` participant lacks the capability it uses (section 6), and any load error
(unresolved reference, cycle, contradictory inheritance).

**No evidence is not support.** A composition in which no vocabulary rule applies — no entries
used, or only entries that declare no requirements, spatial facts or claims for what they bind — is
`unknown` with the finding `no_vocabulary_evidence`, never `feasible`. A status other than `unknown`
always rests on at least one declared rule.

**Input errors are not statuses.** A malformed composition raises an error instead of reporting a
status: an unknown entry, slot, body, item, space or capability; an id bound to a slot of the wrong
kind (a cast member in an object slot); duplicate ids. A well-formed composition that breaks a
declared rule, such as an unfilled required slot, is a `conflict`.

## 4. Participants and references

A slot is single (`"count": 1`) or a group (`"count": {"min": 3, "max": 12}`). Its `kind` is
`being` or `object`.

Reference grammar (used in `requirements`, `spatial`, `claims`):

| Form | Means |
|---|---|
| `front` | a single slot |
| `member[0]`, `member[2]` | one member, **zero-based**, in the order the cast is bound |
| `member[-1]` | counted from the end (`-1` is the last) |
| `member[*]` | each member, one by one |
| `member[1:4]` | members 1, 2 and 3 (half-open range; either bound may be omitted) |
| `member[i]` with `member[i+1]` / `member[i-1]` | each member paired with its neighbour |
| `center` | the centre of the space the position occupies |
| `self` | in a posture: the participant that takes the posture |

Rules:
- A literal index must exist for every allowed size: `0 <= n < min` and `-min <= n < 0`.
- `i` is bound once per rule and ranges over all members. Relative forms (`i+1`, `i-1`) need the
  slot's `topology`: with `"ring"` they wrap (`member[count-1]` pairs with `member[0]`); with
  `"chain"` a pair whose neighbour falls outside the group is skipped. Without a topology, relative
  forms are invalid.
- **Partial participation:** a rule applies exactly to the members its reference matches. Members
  no rule matches are unconstrained; the director decides what they do. A slot whose count allows
  zero (`"min": 0`) is optional.

**Candidate bindings.** When the resolver proposes bindings of a cast to one entry, binding uses
capabilities only, never gender, species or labels. A single slot takes one member; a group slot
takes **any subset** of the members not already bound whose size fits its `count`, so a group never
has to consume the whole remaining cast and cast members may be left out of the entry. Members of a
group keep the cast's order (reorder the cast to try other orders); each subset appears once. An
optional slot may stay empty. The search resolves at most `limit` bindings. When it stops with
bindings left unevaluated it reports `truncated`, and a truncated search is **never** evidence that
no binding works: its `viable` answer is "yes" if a searched binding is not a `conflict`, otherwise
undetermined. Only a complete search with every binding in `conflict` (or none possible) answers
"no".

## 5. Resources and claims

A body owns concrete resource instances (`hand.left`, `hand.right`, `mouth`), each with a capability
`type`. A claim asks for instances of a type on one participant:

```json
{ "resource": "core:limb.hand", "count": 1, "mode": "exclusive", "purpose": "hold", "key": "hold:{object}" }
```

- The resolver allocates specific instances. An exclusive instance is allocated once; a shared
  instance may serve several shared claims but never an exclusive one as well.
- Postures claim too: all fours claims both hands as support, sitting claims the ass. A claim
  for a hand that is already supporting the body is a `conflict`.
- **Intentional sharing:** claims on the same participant with the same `key` are one claim — the
  same instances, counted once. They must agree on `resource`, `count` and `mode`, or it is a
  `conflict`. `{slot}` in a key is replaced by the entity bound to that slot, so "hold the toy"
  and "use the toy" share the hand when, and only when, they are bound to the same toy.
- A claim whose key names an optional slot (`"min": 0`) that is not bound is dropped.

## 6. Spatial frames

Directional relations are evaluated in a fixed frame per relation:

| Relation | Frame |
|---|---|
| `in_front`, `behind`, `left_of`, `right_of` | the body frame of the `of` participant: where that body's front points; left and right are its own |
| `above`, `below`, `on`, `under` | world frame: gravity points down |
| `around` | centred on `of` (`center` or a participant), members spread evenly |
| `between` | between the two participants listed in `of` |
| `astride` | on top of `of`, one leg on each side of the named region |
| `beside` | alongside `of`, without selecting its left or right side |

`facing` is `toward`, `away_from` or `same_as` another reference (body frames), or a world value:
`up` (face up), `down` (face down), `level`. Left and right always mean the participant's own
sides, never the viewer's. Camera framing is a separate visual component (section 11), not a body relation.
Distance is `contact`, `arm`, `near` or `far`.

`access` appears in two places with one shape. In `spatial` it is a declared fact: `from` can reach
**all** listed `regions` of `to` using the capability. In `requirements` it is a need: `from` must
reach **at least one** listed region. `kind` is `touch` (contact) or `sight` (clear line of sight).
A declared access presupposes its capability: the `from` participant is checked for `using` like an
`all_of` requirement (absent is a `conflict`, undeclared is `unknown`).

## 7. Inheritance

`extends` lists parents, resolved in order, depth first. Cycles are a load error. Merging:

| Data | Rule |
|---|---|
| `aliases`, `tags`, capability lists (`provides`, `implies`, and `complete_for` on bodies and objects) | union |
| `requirements` | AND of all parents; a child may only add. `all_of` and `none_of` lists are united. Each inherited `any_of` list stays a separate group, and **every group must be satisfied** (one capability from each). `all_of X` together with `none_of X` is a load error |
| `spatial` values (posture, facing, anchors) | parents must agree or leave them unset; two different values are a load error unless the child sets the value itself. A child may never remove an inherited requirement or anchor |
| `body.resources` | union by instance id; the same id defined differently is a load error |
| `participants.slots` | union by slot name; the same slot with a different count or kind is a load error |
| `claims` | concatenated, then checked for over-allocation at composition |
| header text (`name`, `description`, `notes`) | the child's own value wins. A child without a `description` takes the first parent's (in `extends` order) that has one |
| `rating` | the resolved entry takes the **strictest** rating of itself and every entry it inherits from, so content never becomes less restricted through inheritance |
| `visibility` | participant regions unite; `whole`, `contact` and `space` hold if any source requires them |
| object and environment `capacity` | parents must agree; an explicit child value is final |
| `visual` | dimension, section, media and people are scalars; parents must agree unless the child sets one. Conflicts and shown regions unite. `shows.whole`, `max_regions`, `space` and `complete` are scalars with the same rule |

Conflicting inheritance is always rejected, never silently overridden.

`abstract: true` marks an inheritance-only template. It remains addressable by descendants but is
excluded from retrieval, composition and Visual Direction. The flag is not inherited: a concrete
child can use the template's components without repeating them. Missing components are unspecified,
not incompatible and not evidence of feasibility.

## 8. Rating

`rating` is a content label: `general`, `mature` (non-sexual mature themes) or `adult`. A pack's
rating is the default for its entries; an entry may only be stricter. Ratings never route
generation: the NSFW switch decided in step 1 controls which ratings are eligible for a run (off:
`general` and `mature`; on: all). The loader, resolver and retrieval behave the same either way.

## 9. Versioning

`spec` is the specification version (1). Packs carry their own semantic `version`. These optional
fields extend spec 1 additively; existing packs remain valid. A loader rejects a spec version it does not know.

`replaces: [old ids]` lets an entry take over retired ids. Registry construction redirects references
in `extends` and components before validation, and `Registry.canonical(id)` resolves stored preferences.
The old id must no longer exist, and two entries cannot replace the same id. Dependencies are checked
against the replacement's actual owner: a pack still must require every owner it references. General's
visual entries replace their former `visual:` ids; the Visual pack keeps atmosphere only.

## 10. Retrieval

Retrieval (`retrieval.py`, text matching in `semantic.py`) picks a small, relevant, checked set of
entries from the run's selected packs for one request. It supplies candidates, not a scene or role
assignment; the composer (section 13) makes those decisions, and an empty result is normal.
Retrieval is local and deterministic: no model, service or
download, and the same request with the same enabled packs gives the same result whatever order the
packs are read in and whatever the hash seed.

**Input.** A request is built from a confirmed Dataset brief (`RetrievalRequest.from_brief`) plus the
active director's instructions. Each text is a source with a weight:

| Source | Weight | Source | Weight |
|---|---|---|---|
| `must` | 1.2 | `fixed` | 0.7 |
| `request` | 1.0 | `randomized`, `characters` | 0.5 |
| `summary` | 0.9 | `director` | 0.4 |
| `rules` | 0.8 | `style` (not `Auto`) | 0.3 |

A term found in several sources counts once, at its highest weight.

**Text relevance.** Each entry is indexed by `name` and `aliases` (weight 3), `tags` (1.5),
`description` (1), `category` and `notes` (0.5), and ranked with BM25. Matching is on stemmed words
(plurals, `-ing`, `-ed`, `-ly`, a final `e`; function words ignored), so "kneels", "kneeling" and
"kneel" match. A spelling variant counts at 0.6 × its similarity, and a compound that starts with the
query word ("spell" in "spellcaster") at 0.5. A multi-word name or alias found in one source counts
in full when its words are contiguous and half when they are only all present. One shared word in a
description is not a match: an entry needs a name, alias, tag or phrase match, or two looser matches.
One word of a multi-word name or alias on its own ("staff" of "Magic staff", "side" of "Lying on the
side") counts only when the request also names, in full, an entry linked to it (its parent, an action
that uses it, a position that takes it): "a mage casting a spell with a staff" finds the staff, "hotel
staff" does not. A one-word name or alias, a tag or a whole multi-word name always counts.
The `director` and `style` texts count only where they name an entry: a tag, a whole one-word name or
alias, or a multi-word name found in full. Their general words ("action", "composition", "face") would
otherwise match the descriptions, categories and longer names of every entry. A director that names an
entry ("favour hugs") still guides retrieval.

**Negation.** `no`, `not`, `without`, `never`, `avoid`, `except`, `nor` and `none` negate the next
three content words of their clause. The scope ends early at a clause word (`and`, `but`, `while`,
`with`, `then`, punctuation) and at a new verb form (`-ing`, `-ed`) unless that verb is itself
negated, directly after the negation or after `or`: "no shirt cuddling a woman" negates only "shirt";
"no toys or kneeling" negates both. Every word of the brief's `avoid` items is negated. A negated
term never counts for an entry. An entry whose name, alias or tag matches a negated term is excluded
("ruled out by the request"); a weaker match halves its score. These matches are whole, normalized
words only, never spelling variants or compounds: "no purses" rules out an entry with the alias
"purse", and "no hands" does not rule out a "Handbag". Only the request's own texts negate:
`director` and `style` are standing instructions, so their "never" and "do not" rule nothing out.

**Related concepts.** An entry also gains relevance through the vocabulary's own links to an entry
the request names (at least half of one of its names or aliases matched):

| Link | Factor | Link | Factor |
|---|---|---|---|
| uses (a capability or posture it references) | 0.5 | parent (an entry it extends) | 0.4 |
| used by, broader, narrower (capability `implies`) | 0.35 | child | 0.3 |
| shares (an item or space and an entry that uses the same capability; 2 to 6 users) | 0.25 | | |

The strongest link adds its factor × that entry's score; the next two add a quarter of theirs. An
entry found only through links needs twice `min_relevance`. Capabilities and bodies (and traits) are
never returned: capabilities only relate entries, and bodies only describe the cast.

**Rating.** The resolved rating (section 7: the strictest in the inheritance chain) must be allowed:
with NSFW off, `general` and `mature`; with NSFW on, all. `allowed_ratings` overrides the switch. A
relevant entry with a disallowed rating is reported as excluded, never returned.

**Relevance floor.** An entry is kept when its score reaches both `min_relevance` and a share of the
best score set by the brief's creativity: Strict 0.30, Balanced 0.20, Creative 0.15, Dice 0.10.

**Cast.** Unless the request gives an explicit resolver cast, retrieval infers one from the brief's
characters through the packs' own entries with a `body` component (bodies, traits, creatures) whose
rating is allowed, matched on names, aliases and tags only. What the label and custom text name comes
first: the matching body with the most resource instances is the character's body, other matches are
traits. Gender is never matched against bodies or anatomy. It only carries what Understanding defines:
`male` or `female` is a human man or woman, `custom` is anything else. So a male or female character
whose label and custom text name no full body plan (only traits, or nothing: "knight", "Ana", "winged
knight") gets the pack body named "human", with any named traits; a named species always wins. A
`custom` character is never made human: one no body matches is undescribed (`"body": null`), so checks
involving it are `unknown`, with a warning naming the character.

**Compatibility.** The `shortlist` best entries are checked with the Phase 3 resolver; the rest are
suppressed. What an entry is comes from its components, never its category:

| Entry | Checked as |
|---|---|
| has participant slots (position, action, gesture) | candidate bindings of the cast (section 4), at most `binding_limit`; unfilled object slots get undescribed placeholder objects. The best binding by status counts |
| uses `self` (a posture) | taken by each cast member; the best member counts |
| object (item) | in the first object slot of each retrieved, non-conflicting entry; the best verdict counts |
| environment (space) | as the space of each retrieved, non-conflicting entry that has a space requirement |
| anything else | `unknown` |

An item or space that no retrieved entry uses is `unknown` ("not checked"). Findings that only
concern the space or objects the scene has not chosen yet are reported as `needs` ("a space with:
wide surface to kneel or lie on"), not as `unknown` about the cast. A `conflict` excludes the entry,
with the resolver's reason naming characters as the brief does. A search that is truncated before
finding a non-conflicting binding gives `unknown`, never `conflict` (section 4). `unknown` entries are
kept unless `include_unknown` is off. The score is multiplied by 1.0 (`feasible`), 0.92 (`eligible`)
or 0.8 (`unknown`).

**Selection.** First, an entry and a descendant (an entry that extends it, directly or not) that are
both relevant are settled, counting the same matches as relevance. The descendant replaces the ancestor
when it matches more of the request: every request term the ancestor matched and at least one more ("a
deep bow" keeps Deep bow, not Bow).
A descendant that declares more does not replace an ancestor the request also names on its own,
outside the descendant's names and aliases ("a polite bow and a deep bow" keeps both). Otherwise a
descendant whose resolved components equal the ancestor's is an equivalent and is dropped. A
descendant that declares more is never dropped because its ancestor is kept; when it matches nothing
beyond its ancestor, the ancestor ranks first ("a bow": Bow, then Deep bow). Then entries are chosen in turn by maximal marginal relevance: score against similarity
to those already chosen (word and linked-concept overlap), with the relevance weight set by
creativity (Strict 0.85, Balanced 0.70, Creative 0.55, Dice 0.45) or `variety`. A candidate is
suppressed, with a reason, when its similarity to a chosen entry reaches `duplicate_similarity` or
when its category already has `max_per_category` entries.

**Match classes.** Every match is classified, and only the class decides what it may do:

| Class | Evidence | What it may do |
|---|---|---|
| explicit | an entry's whole name or alias in the brief's own words, in order and adjacent: articles, pronouns and possessives may sit between its words and the brief's own cast words stand for a participant ("sitting on a man's lap" holds "Sitting on a lap"), but a preposition or conjunction (`STRUCTURAL`: at, by, for, from, in, into, onto, on, off, out, to, with, within, about, of, and, or, but) is structure: the name must have one in the same place, any one ("sitting in his lap" holds it too), so "a book in the corner" does not hold "Book corner". Theme and tag phrases are matched the same way, or a whole one-word name or alias in the same word or a close spelling, never a compound ("play" is not "playroom") | named for every image; decides the interaction, place or item for the ideas when the request states a choice and the entry survives rating, exclusions and compatibility; reaches its pack's theme as an entry; found whatever its pack's activation |
| contextual | a tag of the entry used in full and in order (a concept), or a word of the entry's text plus a relation the packs declare to an explicit entry: it extends it or is extended by it, it provides what the explicit entry requires of an object, or it is the posture the explicit entry takes | an optional idea (scope `related`) where its category is open or for itself; never named, never deciding; a tag reaches its pack's theme as a concept, other relations count only inside a pack already reached; listed in `intent.related` with why |
| weak | anything else: one word of a longer name, alias or tag, a compound, description words, a capability two entries share | nothing; the best are listed in `intent.rejected` with why |

A tag is a concept, never a name. Capabilities decide compatibility, not what the request asks for.
The brief's own `fixed`, `must` and `avoid` texts stay the user's requirements whatever the vocabulary
matched: what the vocabulary decides only closes categories of optional ideas.

**Inspiration.** Besides the entries a request names (`source: "direct"`), retrieval offers ideas
(`source: "inspiration"`) from the categories the brief opens, so a broad request ("two adult men
having sex", "epic fantasy scenes of a dragon") gets varied, checked suggestions without naming any
entry, category or place. Intent comes only from the brief's own texts (`request`, `summary`, `must`,
`rules`, `fixed`, `randomized`) and its cast, never from `director` or `style`, and only from what the
packs declare; nothing is special-cased for a pack, a category name or a word. These scopes reach
entries; all but `content` open them:

| Scope | Reached when | Weight |
|---|---|---|
| category | a word of the category's declared name, or a description word no other declared category uses ("sex positions" reaches Positions; "location" reaches Spaces through "locations, settings and environments") | 1.0 |
| arrangement | the brief has people: every image arranges them, so a position (a bindable entry that places its participants without claiming body resources) whose slots hold exactly this cast, or for one person a posture, is open unless the brief fixes the interaction | 1.0 (counted once with category and setting) |
| setting | the brief has people and sets no place: every image has a place, so spaces are open | 1.0 (counted once) |
| theme | what the brief asks of a pack. **Broad**: its name or a declared `themes` phrase, as an ordered phrase of the brief's own words that nothing negates or avoids; it reaches every entry of the pack. **Concept**: a tag (as an ordered phrase, `_` as a space) carried by some of its scene entries; it reaches just those entries. **Entry**: an entry it declares that the brief names, or a cast body or trait other than the plain human body; it reaches that entry and the entries of the same pack it explicitly extends or that extend it, never siblings under a shared parent. Capabilities decide compatibility, not relevance, so a shared capability reaches nothing. A pack's description never reaches anything. A rating word ("adult") is the content level, never a theme. The mandatory core has no theme | 0.75, added to the content level: what the brief asks for ranks above what it merely allows |
| content | an NSFW brief puts entries of the top allowed rating on topic. It never opens a category: it ranks what the other scopes opened, so a broad sexual request gets sexual positions first (only from packs with content activation, section 1), and acts, accessories or restraints only when the brief's words or a theme ask for them | 1.0 |

Acts (bindable entries that claim body resources) and items are opened only by the brief's words or a
theme. An entry of a pack that has a theme (every pack but the core) needs the brief to reach it through
that theme (broad, or its concept or entry), or the content level when its pack declares
`activation: "content"` (section 1). A relevant entry the named entries leave out (over the
per-category limit) stays on offer as an idea when the brief asks for it as a concept or entry. Without people nothing is opened by the scene's dimensions: a still life gets no invented place.
What the brief fixes stays fixed, by kind (components), never by category name:

- a position, action or posture the request, summary, must, rules or fixed text names fixes the
  interaction: no position, action or posture ideas ("in missionary" offers no other position or act);
- a space it names fixes the place, an item it names fixes the item;
- a place in words the vocabulary does not know is only a guess: a locative phrase (`in`, `on`, `at`,
  `inside`, `under`, `near`, … and up to two content words) whose words name no entry the request names
  or casts and reach no category ("on a train platform", "in a dark forest"). It keeps place ideas back
  (the error is to suggest less) but is reported in `intent.uncertain` as an uncertain text guess, never
  in `intent.fixed`: text alone cannot tell "in a garden" from "at play" or "in love". "In missionary"
  and "on a bed" are explained by their entries; "in different locations" reaches Spaces and opens them;
- a category the `randomized` text reaches is open even next to a named choice ("a couple kissing",
  randomized "positions": positions open, actions stay fixed);
- a negated or `avoid` word that reaches a category closes it ("no accessories").

**What the request rules out** reaches through the vocabulary's dependencies. An entry whose name,
alias or tag a negated or `avoid` word names is ruled out. So is every item that provides a capability
such an entry requires of its objects (`all_of` or `any_of`, with `implies`), unless an entry the request
names needs that capability too: "no toys" rules out Toy play and with it the dildo, vibrator and
strap-on, even next to a named Hold that could take them, while a book stays. And an interaction whose
required object (at least one) only ruled-out items provide is ruled out ("no fire pit" rules out
warming hands at it). Named entries are never ruled out by this, and a ruled-out idea is reported in
`excluded` with the reason.

Every candidate is checked like a named entry, with no top-N: every position, action and posture first
(conflicts are excluded with `source: "inspiration"`), then the spaces and items. A space is checked
here with the interactions the request names (a conflict excludes it), and otherwise `eligible` with
the note that it is checked per image. An item is kept when it is checked to serve at least one
interaction of the pool (`eligible` or `feasible` for that pair); `attach_to` lists every interaction
whose object slot asks for nothing the item lacks (a necessary condition, so no pairing the resolver
would accept is missed). The score is the scope weight (plus a little of any partial text match),
× the status factor, × 0.6 + 0.4 × the share of the cast the idea involves. Repeats
(`duplicate_similarity`) and equivalent descendants are suppressed; everything else stays in the pool,
whatever its size and however far below the best it scores (`stats.eligible` counts it per category).
Relevance decides what is a candidate; the score only weights it.

**Rotation.** Each scene gets its own ideas (`ideas(n)`, `scenes(count)`), a coherent set rather than
competing alternatives: at most one idea per role. The role comes from components, never the category:
a space is the place; a posture, or a bindable entry that places its participants without claiming body
resources, is the arrangement; any other bindable entry is an interaction. So places from several packs
and categories share one slot, and one image gets at most one place. Each scene draws one idea per role
from the role's whole pool (all its categories together): each entry draws an exponential key,
−ln(u) / (weight × staleness), where u comes from a stable hash of the seed, role, scene and entry id, and
the lowest key wins, so an entry wins with probability weight × staleness ÷ total. The weight is the score
to the creativity's power (Strict 3, Balanced 2, Creative 1.5, Dice 1); staleness is 1 + (picks since it
was last offered) ÷ (its category's size), at most 2, and 2 for one never offered, so among comparable
ideas the least recent is likelier. After being offered an idea rests for ⌊cooldown × (size − 1)⌋ picks
of its role, at least one, where size is its own category's size (a category of one does not rest) and
the cooldown comes from creativity (Strict 0.25, Balanced 0.50, Creative 0.65, Dice 0.80). A scene takes
the first entry by key that fits: rested and not the previous pick; else any but the previous pick; else
any. So a better-matched idea comes more often, not only earlier (an idea can come at most once per rest
+ 1 picks), every eligible idea keeps a chance, two compatible ideas alternate, a single one repeats, and
a scene is never left without an idea because of a cooldown. A place must fit the interactions of its
scene (no conflict with any that needs a space) and an item must be checked to serve one of them; these
per-image checks are cached by pair, and fitting is never relaxed for variety (no fitting entry, no
idea). A scene's ideas depend only on the brief, the packs, the seed and its number, computed from scene
1: never on which scenes were asked for before, in what order, or which images failed. Creativity sets the most ideas per scene (Strict 2, Balanced 3, Creative 3,
Dice 4); a scene never gets more than one per open role, so fewer roles give fewer ideas, never filler.
Roles the brief's own words (or its theme) reach come first, then the open arrangement, then the open
place; roles of one rank that do not all fit take turns by scene. A scene lists its interaction, then its
arrangement, then its place. Fewer ideas than scenes simply repeat. An item comes along
only in a scene that holds an interaction it serves (named or an idea), at most one per scene.
`offer(numbers)` renders the block for one model request writing those scenes: the named entries for
every image, the ideas per concept of that request, and each idea described once. Without ideas it
is exactly `render()`. Freeform images receive their own offer during concept and staging requests.
Composed images instead receive authoritative scene facts in the finisher; the Vocabulary inspector
shows retrieval results and a per-scene preview.

**Result.** `entries` (best first: id, name, category, pack, rating, description, status, relevance,
score, why, warnings, needs, binding, checked_with, source, scopes, attach_to), `inspiration` (the
ideas, per category, best first), `intent` (`content`, `themes`, `fixed`, `ruled_out` and every scene
category with what reached it, whether it is `open`, `closed` or `not reached`, its ideas and, when it
has none, why), the inferred `cast`, `suppressed`, `excluded`, `warnings` and `stats`. An empty result
(no entries and no ideas) carries one warning: no packs are enabled, the request has no searchable
words, nothing is relevant, or nothing relevant is compatible. `render()` gives a short reference
block of the named entries for a prompt, at most `max_chars`, or `""` when nothing was retrieved. It
lists each entry's name, description, status and up to two needs, says that `feasible` is not proof,
and never assigns roles or characters.

| `RetrievalConfig` | Default | `RetrievalConfig` | Default |
|---|---|---|---|
| `max_results` | 6 | `binding_limit` | 48 |
| `max_chars` | 1200 | `min_relevance` | 1.5 |
| `max_per_category` | 2 | `duplicate_similarity` | 0.7 |
| `shortlist` | 24 | `include_unknown` | true |
| `inspiration` | true | | |

Paraphrases are not understood: a request reaches an entry only through words its pack declares.
A structured interpretation of the request (mapping its meaning onto declared concepts) would be a
separate step; text-only retrieval stays the fallback.

Retrieval matches words, not meaning: a request that describes an entry only in words none of its
names, aliases, tags, description, notes or links use will not find it, and a category or pack theme
is only reached through the words its manifest declares. Pack authors should give entries the aliases
and tags people actually write, categories names and descriptions in the words briefs use, and packs a
name and `themes` that ask for the pack as a whole.

Pack isolation: a pack a request does not reach changes neither its named entries nor its ideas, their
scores, the categories the request opens or the links between entries; disabling it again restores the
same results. Everything an entry's retrieval depends on is computed within its own pack's closure (the
pack and the packs it requires, directly or not): an entry is scored (BM25 term rarity and average length)
against the entries of that closure; a category's description word is distinctive when no other category
declared in its pack's closure uses it; and a capability is common (more than six users, so it relates
nothing) when counted among the entries of the two packs' closures. A pack whose entries the request does
match competes as before, and two matching packs both contribute.

Known limitations, kept for the later semantic integration. A place the engine only guesses from the
request (labelled uncertain) still holds the place role, so optional place ideas are suppressed even when the
guess is wrong. Prepositions are matched as one interchangeable marker so that "sitting in his lap" and
"sitting on his lap" both match; the same freedom can match a phrase with the wrong spatial relation
("under the table" for "on the table").

## 11. Visual Direction

A `visual` component makes an entry a visual direction: how an image is seen and lit, never what is in it.
`dimension` is the one choice it fills (`framing`, `camera_angle`, `composition`, `lighting`, `atmosphere`);
`section` is the scene field it guides (default `lighting` for lighting and atmosphere, `camera` otherwise);
`media` limits it to these styles (`anime`, `realistic`, `illustration`, `3d`, `product`, `painting`; absent:
every style); `people` can limit non-framing directions to casts of `min` to `max` people per image;
framing is never rejected solely by head count. `conflicts` lists directions it never shares an image
with (they hold both ways and must be directions). General owns concrete framing, camera angles, composition and
lighting; the official `visual` pack owns atmosphere. Any selected pack may add directions within its allowed ratings.

`shows` optionally declares visibility capabilities: `whole` (whole bodies), `regions` (capability ids),
`max_regions` (a detail crop's region limit), `space` (place in view), and `complete` (the regions list is
exhaustive). Missing fields leave that capability unknown. `visual.fit` compares these declarations with
the composed scene's visibility (section 12); it does not infer geometry, occlusion or physical plausibility.

Retrieval (section 10) never indexes, scores or offers a direction, and a category holding only directions is not
one a brief opens: content retrieval is the same with or without them. Visual Direction (`visual.py`) chooses them
for each Dataset image, from the confirmed brief alone (no model, no semantic hints):

1. The brief comes first. A direction its request, fixed, must or rules name (by name or alias, the longest match
   winning) is used in every image (several: they take turns). A dimension it mentions only in general, by the
   dimension's or its category's name as written ("dramatic lighting"), is left to the brief. Directions the
   randomized text names are the ones that take turns; a dimension it mentions stays open. Avoid phrases and
   negations ("no dutch angle") rule directions out.
2. Per run, each dimension can be off and has a variation: `same` (one direction), `low` (two take turns), `medium`
   (four), `high` (all that fit) or `auto` (Strict low, Balanced medium, Creative and Dice high).
3. A direction must suit the style, any non-framing cast limits and the image's other directions; named
   directions are placed first. Open dimensions exclude directions whose `shows` contradicts the composed
   scene's visibility. Unknown visibility capabilities remain eligible. User-named directions are kept even
   against visibility requirements; the brief wins. Director preferences rank pools and avoid directions,
   but never overrule a user-named choice.
4. Image N's directions depend only on N, the seed, the brief, the settings and the selected packs, never on other
   images: each cycle through a dimension's pool uses every direction once, in an order seeded per cycle.

For composed images, directions accompany each scene's checked facts in the finishing request. Freeform
images receive `visual_direction` in the concept request and carry camera and lighting through staging and description; the request,
fixed, must, avoid and rules outrank them and they never change the place, position, people or actions. While Visual
Direction is active, what the brief says about the camera or light (the matched names and dimension words) is
masked out of content retrieval only, so "low camera angle" never finds a Camera prop. Every choice, pool,
exclusion and reason is kept in the run's vocabulary diagnostics.

## 12. Visibility and capacity

`visibility` describes what an entry needs in view, without choosing a camera:

```json
{"participants": {"actor": {"regions": ["core:limb.hand"], "whole": true}},
 "contact": true, "space": true}
```

Participant references use section 4's slot and group grammar. `contact` adds both sides of each declared
or required access: the source's `using` part and the target's regions. `space` requires the place in view.
The resolver collects these into `Resolution.visibility`, bound to individual cast ids; it does not
claim they are visible. The composer passes them to `Plan.see(image, visibility)` before visual selection.

Objects and environments may declare `capacity: {"beings": N}`. A space's capacity counts the cast; an
item's capacity counts distinct beings anchored `on` or `astride` that item. Exceeding a declared capacity
is `over_capacity`, a conflict. An absent capacity imposes no limit. No room size, body size, distance,
surface load or occlusion is inferred from prose.

## 13. Scene composition and Directors

Dataset V2 follows Understanding → structured scene contract → vocabulary retrieval and joint composition → finishing → target-specific Builder
prompt. `features/vocabulary/composer.py` composes each image deterministically from the confirmed brief,
retrieval result, selected packs, Director preferences and seed. It never calls a model.

Roles come from components, not category names: an environment is a space, an object an item, a self
placement a posture, and a bindable entry with spatial data but no claims an arrangement; other bindable
entries are interactions. Items fill interaction object slots. The default selection order is arrangement,
interaction, space; Director priorities can reorder it. Every trial binding is resolved with the scene so
far, including placements, resources, access, surfaces and capacity. Conflicting trials are never selected.
Search backtracks across entry choices, role assignments, objects and spaces; it does not lock the first
nonconflicting binding. Complete feasible results outrank eligible and unknown results. Search is bounded;
exhaustion is reported as unchecked, not proof of incompatibility. Unknown results have no verified claim.

The brief's named entries are established before optional choices can consume their resources.
Names matched by the same words are alternatives, even across
roles; unrelated named actions are separate requirements. A longer matched name is not an invitation to
substitute its shorter substring. Guided images require the entries their own input names and keep shared
fixed, must and rule requirements. An unsatisfied requirement fails that image with its reason rather than silently substituting an
unrelated scene. Grounded Understanding performer/target links constrain bindings when the entry declares
those sides through access, participant `role: "performer" | "target"`, or a sole being slot; an incompatible
assignment cannot silently swap people. Multiple performer slots support symmetric activities. Confirmed
pairwise spatial relations are compared with direct and reciprocal anchors. Missing mechanics
stay open. Images unsupported by vocabulary use concept → staging → description, marked `freeform` and
`unchecked`, not described as vocabulary-verified. A failed image never shifts later slot numbers.

The finisher receives selected names, roles, declared facts, items, place and visual direction. It adds
appearance, open per-person details, place detail, lighting, mood, camera and background. It cannot replace
the structured mechanics: code renders positions and actions from the composition and retains its
established place and camera/light fields. Final scenes keep
entries, roles, facts, status and the limits of checking. The Builder receives those facts and keeps them
as verbatim locked clauses while writing the surrounding prompt in the selected target's format.
Missing clauses trigger a retry, then a failed prompt, not silent acceptance. Added prose is not semantically validated; passing a
contract check does not prove that a model's prose obeys every instruction.

A Director preset may carry an optional `vocabulary` block:

```json
{"require": ["general:action.hold"],
 "prefer": {"entries": ["general:action.hug"], "tags": ["friendly"], "categories": ["position"]},
 "avoid": {"entries": [], "tags": [], "categories": []},
 "visual": {"prefer": ["general:lighting.soft"], "avoid": []},
 "priorities": ["interaction", "arrangement", "space"],
 "themes": ["quiet afternoons"]}
```

All keys are optional. `require` declares mandatory entry ids, not weighting. Missing required ids are
reported as unsupported in an unchecked fallback. Grounded fixed Understanding actions must match
activity names/aliases, not related descriptions, tags or semantic hints. A noun cannot satisfy an action.
An explicit opening imperative in Director prose can name pack-defined requirements; arbitrary prose
is not a general-purpose constraint language. Use `require` for reliable mechanical obligations.
Entries combining `visual` with participant/resource/object components enter joint composition only
when required, not random activity inspiration. Their inherited mechanics and visual coverage are
resolved together; purely visual entries remain Visual Direction choices.

Preferences are validated data: ids, tags and categories to favour or avoid;
visual ids; composition role priorities; and short theme phrases. Preferred ideas get increased draw
weight. Avoided ideas are omitted unless the request names them. Preferences never enable unselected
packs or bypass ratings, exclusions or compatibility. Unknown preference ids are unused and reported. Retired ids
are canonicalized. Presets without a block still steer retrieval through their text. Saving and editing
preserves the block; an omitted update keeps it, `{}` clears it. Built-in Directors use the same format,
not engine conditionals keyed by Director id.
