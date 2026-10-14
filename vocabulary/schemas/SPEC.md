# Vocabulary specification, version 1

Vocabulary packs are optional, declarative knowledge for the Dataset director: bodies, postures,
positions, actions, objects, spaces and the capabilities that connect them. A pack never
prescribes a scene, never decides whether a request is NSFW, and never contains code. With no
packs installed, generation works exactly as without vocabulary.

Files:

| File | Contract |
|---|---|
| `manifest.schema.json` | `manifest.json` of every pack |
| `entry.schema.json` | every entry file (`{"spec": 1, "entries": [...]}`) and every entry |

Locations: the built-in pack is `vocabulary/core/`. User-installed packs live in the Git-ignored
`data/vocabulary/packs/<pack-id>/`.

## 1. Packs

A pack is a folder with `manifest.json` and the entry files it lists. `id` is the pack's
namespace. `requires` maps pack ids to version ranges (`>=1.0.0 <2.0.0`). `categories` declares
the groupings the pack introduces; any loaded pack may use a category declared by itself or by a
pack it requires. Categories only group entries for retrieval and the UI: **the engine never
branches on a category**. Behaviour comes only from an entry's typed components.

## 2. Entries

Every entry has the same header (`id`, `category`, `name`, `description`, `aliases`, `tags`,
`rating`, `extends`, `notes`) and a `components` object. Unknown keys are rejected everywhere.

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

A capability is provided by a body through the types of its resource instances, its `provides`
list, and everything those capabilities imply (transitively).

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

`facing` is `toward`, `away_from` or `same_as` another reference (body frames), or a world value:
`up` (face up), `down` (face down), `level`. Left and right always mean the participant's own
sides, never the viewer's. Camera framing is not part of vocabulary; it belongs to the director.
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

Conflicting inheritance is always rejected, never silently overridden.

## 8. Rating

`rating` is a content label: `general`, `mature` (non-sexual mature themes) or `adult`. A pack's
rating is the default for its entries; an entry may only be stricter. Ratings never route
generation: the NSFW switch decided in step 1 controls which ratings are eligible for a run (off:
`general` and `mature`; on: all). The loader, resolver and retrieval behave the same either way.

## 9. Versioning

`spec` is the specification version (1). Packs carry their own semantic `version`. New behaviour
arrives as new components in a later spec version; a loader rejects a spec version it does not know.

## 10. Retrieval

Retrieval (`retrieval.py`, text matching in `semantic.py`) picks a small, relevant, checked set of
entries from the enabled packs for one request. It assists and never decides: it does not choose a
scene, position, cast or role, and an empty result is normal. The director then writes an original
scene exactly as without vocabulary. Retrieval is local and deterministic: no model, service or
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
| shares (both use a capability that 2 to 6 entries use) | 0.25 | | |

The strongest link adds its factor × that entry's score; the next two add a quarter of theirs. An
entry found only through links needs twice `min_relevance`. Capabilities and bodies (and traits) are
never returned: capabilities only relate entries, and bodies only describe the cast.

**Rating.** The resolved rating (section 7: the strictest in the inheritance chain) must be allowed:
with NSFW off, `general` and `mature`; with NSFW on, all. `allowed_ratings` overrides the switch. A
relevant entry with a disallowed rating is reported as excluded, never returned.

**Relevance floor.** An entry is kept when its score reaches both `min_relevance` and a share of the
best score set by the brief's creativity: Strict 0.30, Balanced 0.20, Creative 0.15, Dice 0.10.

**Cast.** Unless the request gives an explicit resolver cast, retrieval infers one from the brief's
characters (label, gender unless custom, and custom text) through the packs' own entries with a
`body` component (bodies, traits, creatures) whose rating is allowed, matched on names, aliases and
tags only. The matching body with the most resource instances is the
character's body; other matching bodies are added as traits. Gender and species never select a body
in code. A character no body matches is undescribed (`"body": null`), so checks involving it are
`unknown`, with a warning naming the character.

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
both relevant are settled. The descendant replaces the ancestor when it matches more of the request:
every request term the ancestor matched and at least one more ("a deep bow" keeps Deep bow, not Bow).
A descendant that declares more does not replace an ancestor the request also names on its own,
outside the descendant's names and aliases ("a polite bow and a deep bow" keeps both). Otherwise a
descendant whose resolved components equal the ancestor's is an equivalent and is dropped. A
descendant that declares more is never dropped because its ancestor is kept; when it matches nothing
beyond its ancestor, the ancestor ranks first ("a bow": Bow, then Deep bow). Then entries are chosen in turn by maximal marginal relevance: score against similarity
to those already chosen (word and linked-concept overlap), with the relevance weight set by
creativity (Strict 0.85, Balanced 0.70, Creative 0.55, Dice 0.45) or `variety`. A candidate is
suppressed, with a reason, when its similarity to a chosen entry reaches `duplicate_similarity` or
when its category already has `max_per_category` entries.

**Result.** `entries` (best first: id, name, category, pack, rating, description, status, relevance,
score, why, warnings, needs, binding, checked_with), the inferred `cast`, `suppressed`, `excluded`,
`warnings` and `stats`. An empty result carries one warning: no packs are enabled, the request has
no searchable words, nothing is relevant, or nothing relevant is compatible. `render()` gives a short
reference block for a prompt, at most `max_chars`, or `""` when nothing was retrieved. It lists each
entry's name, description, status and up to two needs, says that `feasible` is not proof, and never
assigns roles or characters.

| `RetrievalConfig` | Default | `RetrievalConfig` | Default |
|---|---|---|---|
| `max_results` | 6 | `binding_limit` | 48 |
| `max_chars` | 1200 | `min_relevance` | 1.5 |
| `max_per_category` | 2 | `duplicate_similarity` | 0.7 |
| `shortlist` | 24 | `include_unknown` | true |

Retrieval matches words, not meaning: a request that describes an entry only in words none of its
names, aliases, tags, description, notes or links use will not find it. Pack authors should give
entries the aliases people actually write.
