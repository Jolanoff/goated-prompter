---
name: vocabulary-pack-creator
description: Create, extend, review, and package Goated Prompter vocabulary modpacks using the repository's authoritative schemas, existing pack conventions, and focused tests.
---

# Goated Prompter — Vocabulary Pack Creator

## Purpose

Create **data-only, installable vocabulary packs** that extend Goated Prompter's reusable knowledge without changing its engine or forcing the Scene Director to follow canned prompts.

Vocabulary provides concepts, capabilities, requirements, resources, and declared spatial facts. It does **not** guarantee physical plausibility. The Director decides how to use relevant knowledge. Unknown information is not an implicit prohibition.

## Mandatory sources (read before writing anything)

Read the **actual current repository files** in this order:

1. `vocabulary/schemas/SPEC.md` — normative semantics, statuses, inheritance, ratings, and references.
2. `vocabulary/schemas/manifest.schema.json` — the accepted pack manifest contract.
3. `vocabulary/schemas/entry.schema.json` — permitted entry fields, typed components, and their exact shapes.
4. `vocabulary/core/manifest.json` and representative core entries.
5. Representative working packs in `vocabulary/packs/` and their manifests.
6. Applicable tests under `tests/unit/vocabulary/` and the installed pack loader's API where necessary.

If a referenced file cannot be accessed, **stop before creating schema-dependent JSON and report the missing reference**. This skill is a workflow guide, not a substitute for the current spec. Never assume an example from a previous chat is valid against the current schema.

Also follow the repository's `AGENTS.md` and mandatory local agent workflows, including any required task approval, GitHub issue and branch rules, resource limits, and privacy restrictions. This skill does not override them.

## First decide the task scope

Determine whether the request is to **create**, **extend**, **review**, **validate**, **package**, or **install** a modpack. Respect that scope. Do not start application code changes, frontend work, model inference, downloads, or unrelated refactors unless separately authorized under the project workflow.

For a new pack, establish its stable ID, purpose, content rating, intended categories, expected dependencies, and a **small initial set of entries**. When unspecified, propose conservative defaults rather than inventing a large taxonomy. Check whether a similar concept already exists in Core or another available pack.

## Pack organization

Use the structure permitted by the current loader and manifest schema. A typical source pack is:

```text
vocabulary/packs/<pack-id>/
  manifest.json
  <declared-entry-file>.json
  README.md                       # only if supported by the loader
```

`vocabulary/core/` is the mandatory built-in core. Bundled optional packs are source-controlled in `vocabulary/packs/` if the current loader supports them; community-installed packs reside in `data/vocabulary/packs/`. Never write directly into private installed packs unless expressly requested and authorized. Do not duplicate built-in entries just to make a pack self-contained: use valid dependencies and references.

All content must be **declarative JSON or explicitly loader-allowed documentation**. Never ship executable code, scripts, prompts instructing the agent to run commands, unexpected files, or unsafe archive paths.

## Entry design rules

1. **Reuse, don't enumerate combinations.** One reusable position/action/ability/object concept should work across compatible characters and settings. Never create separate entries solely for every gender, species, participant count, or environment combination.
2. **Separate identity and anatomy.** Character labels, pronouns, identity, bodies, and traits are distinct. Do not infer a person's anatomy solely from gender.
3. **Separate actions, positioning, objects, and environments.** Describe each in the correct typed component; reference existing entries using qualified IDs. Avoid copying their declarations into every entry.
4. **Use capabilities and requirements declaratively.** Express what an entry supplies and needs, using only capabilities that exist in the registry. Never invent undocumented keys, operators, component types, or spatial relations.
5. **Declare only evidence you know.** `feasible` means declared constraints match, not that physical geometry has been proved. Incomplete knowledge should remain `unknown` where the spec requires it; don't add arbitrary restrictions to force a result.
6. **Respect resource ownership.** If an action occupies a hand or other exclusive resource, use the existing claims mechanism, including intentional sharing keys only for the same real allocation.
7. **Make retrieval discoverable but precise.** Names and aliases are what a request names explicitly: give each entry the whole phrases people write for it, not a bare body part or a generic word (an alias "toes" on an action would make "toes" ask for that action). Tags are concepts that offer entries as optional ideas (`feet`, `pet_play`). `extends`, object requirements and the postures a position takes are the relations that tie a partial match to a named entry; a shared capability never does (SPEC.md section 10, match classes). Use natural names and a few accurate aliases/tags. Do not keyword-stuff, add unrelated terms, or rely on generic words to make every request match. A pack's name and its manifest `themes` (e.g. `["cyberpunk"]`) are the phrases that ask for the whole pack; its description is never matched. Put a specific concept on the entries that carry it as a tag (`feet`, `pet_play`), so a brief asking for it gets those entries and not the rest of the pack. A category's name and description are how broad briefs open it for inspiration (SPEC.md section 10): describe categories in the words briefs use ("locations", "props").
8. **Keep descriptions useful and concise.** A vocabulary entry should describe a reusable concept—not a complete scene, camera script, or multi-image prompt. Avoid redundant sentences across entries; use inheritance when appropriate and supported.
9. **Use correct ratings.** Match `general`, `mature`, or `adult` as defined by the spec. An entry must never loosen inherited or pack-level restrictions. Rating labels control eligibility, not user intent classification. Leave the manifest's `activation` at its default (`theme`) unless the pack is general content for its rating that every NSFW brief may draw on (SPEC.md section 1); specialised or opt-in packs keep `theme`.
10. **Visual directions are not scene content.** Camera angles, framing, composition, lighting and atmosphere go in a `visual` component (SPEC.md section 11), never as items or spaces: a camera angle is not a Camera prop. Write their descriptions without photographic terms unless `media` limits them to photographic styles.
11. **Prefer a small coherent pack over a giant untested list.** Add entries incrementally, with meaningful constraints and realistic retrieval cases.

## Build workflow

### A. Inspect and inventory

Read the schemas and relevant existing entries. Make an inventory: what is already defined, what is genuinely missing, and what dependencies are required. Look for aliases, capabilities and inheritance opportunities before proposing new IDs.

### B. Design a minimal pack

Create the manifest in the **exact current schema**, declare only the category and entry files used, and reference required packs with compatible version constraints. Draft a small coherent set of entries using valid typed components. Use unique stable IDs and consistent names. Avoid duplicating concepts provided elsewhere.

### C. Check compatibility and retrieval

For representative requests, determine what should be retrieved, what should **not** be retrieved, and whether compatible composition statuses should be `conflict`, `unknown`, `eligible`, or `feasible` under the spec. Cover optional/solo/group participants, missing capabilities, explicitly absent capabilities, resource clashes, and cross-pack references when relevant. Do not claim to have run the resolver unless you actually executed it.

### D. Validate

With the user's approvals and available environment:

- Parse all JSON and validate manifests and entries against the real schemas.
- Load the new pack with its real dependencies using existing loader interfaces.
- Check IDs, references, inheritance, ratings, cycles and loader file rules.
- Run focused vocabulary contract/loader/resolver/retrieval tests appropriate to the change.
- Add specific regression tests for new intended matches **and** obvious false positives.
- Confirm an unrelated SFW request does not receive irrelevant or adult-rated suggestions.
- If any command is unavailable, say exactly what was not tested. Do not mark skipped tests as passes.

The existing vocabulary unit-test command, if still applicable to the current repo, is:

```bash
python -m unittest discover -s tests/unit/vocabulary -t .
```

Check the repo's current test instructions before running it.

### E. Package only on request

If asked to distribute, use the loader's accepted archive structure and allowed files only. Do not include `data/`, `.git/`, caches, build results, machine paths, secrets, executable files or symlinks. Test the ZIP through the actual pack loader when possible.

### F. Report and stop

Report the pack's ID, version, rating, dependencies, entry counts, changed files, example matched and rejected queries, validation/test results, and remaining unknowns. Stop at the requested scope. Do not install the pack into a user's private data, commit, push, run GPU inference, or start other phases without authorization.

## Definition of done

A pack is ready when its files obey the current schema and loader rules, its references and dependencies resolve, representative retrieval tests show **useful matches without unrelated suggestions**, ratings work, and its entries add reusable knowledge rather than full canned scene combinations. A passing schema test alone is not proof that generated images improve; quality requires separate controlled evaluation.

## Red flags: stop and redesign the entry, not the engine

- Many almost-identical entries differing only by character gender or wording.
- A scene-sized prompt embedded as a vocabulary definition.
- A new Python conditional needed for a particular genre or kink.
- Unknown capabilities treated as impossible without declared completeness.
- A position asserting real-world feasibility solely from tags.
- Generic aliases causing unrelated requests to retrieve an entry.
- New components or fields not defined in the current schema.
- More than a small initial pack added before validating a realistic retrieval sample.

**Core principle:** Packs declare reusable knowledge; the resolver evaluates declared constraints; retrieval suggests relevant entries; the Director remains creative and the user's latest request remains authoritative.
