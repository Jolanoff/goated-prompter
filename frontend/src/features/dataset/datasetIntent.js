// Understanding v10: corrections to a brief's structured intent at confirmation. The server checks every
// correction again (goated_prompter/features/dataset/v2/intent.py reviewed); these helpers only offer the
// edits it allows: search words, participant identities, links, removing suggestions and dismissing notes. Anything
// the request states is changed with Revise.

export const intentKinds = { subject: "People and subjects", action: "Actions", pose: "Poses", object: "Objects",
  body_part: "Body parts", attribute: "Attributes", environment: "Places", aspect: "Look and camera" };
export const intentStatus = { fixed: "Every image", randomized: "Varies", optional: "Allowed", excluded: "Ruled out" };
export const MAX_TERMS = 6;

const update = (intent, id, patch) => ({ ...intent, elements: intent.elements.map((item) => item.id === id ? { ...item, ...patch } : item) });

/** Subjects use their bound identities; belongings use that same name: "neck (man 2)". */
export function partName(intent, id) {
  const item = intent.elements.find((element) => element.id === id);
  if (!item) return id;
  if (item.kind === "subject" && item.cast.length) {
    return item.cast.length === 1 ? item.cast[0] : `${item.text} (${item.cast.join(", ")})`;
  }
  const owner = item.of && intent.elements.find((element) => element.id === item.of);
  return owner ? `${item.text} (${owner.kind === "subject" ? partName(intent, owner.id) : owner.text})` : item.text;
}

/** "woman → kisses → neck (man)", "reads", ... for one part. */
export function partSentence(intent, item) {
  const names = (ids) => ids.map((id) => partName(intent, id)).join(", ");
  return [item.by.length ? names(item.by) : "", partName(intent, item.id), item.to.length ? names(item.to) : ""].filter(Boolean).join(" → ");
}

export function memberChoices(item, characters) {
  const key = item.character.toLocaleLowerCase();
  return characters.filter(({ label }) => label.toLocaleLowerCase() === key || label.replace(/ \d+$/, "").toLocaleLowerCase() === key)
    .map(({ label }) => ({ label, member: Number(label.match(/ (\d+)$/)?.[1] || 0) }));
}

export function setMember(intent, id, member, characters) {
  const item = intent.elements.find((element) => element.id === id);
  const choices = memberChoices(item, characters);
  return update(intent, id, { member, cast: choices.filter((choice) => !member || choice.member === member).map(({ label }) => label) });
}

export function groupedParts(intent) {
  return Object.keys(intentKinds).map((kind) => [kind, intent.elements.filter((item) => item.kind === kind)])
    .filter(([, items]) => items.length);
}

export function canRemovePart(intent, item) {
  return item.source === "suggested" && !intent.elements.some((other) => other.of === item.id || other.by.includes(item.id) || other.to.includes(item.id))
    && !intent.relations.some((relation) => relation.a === item.id || relation.b === item.id);
}

export function removePart(intent, id) {
  return { ...intent, elements: intent.elements.filter((item) => item.id !== id) };
}

export function setTerms(intent, id, text) {
  const terms = [...new Set(String(text).split(",").map((term) => term.trim()).filter(Boolean))].slice(0, MAX_TERMS);
  return update(intent, id, { terms });
}

/** Link choices for a field: subjects for by, any other part except attributes and looks for to. */
export function linkChoices(intent, item, field) {
  return intent.elements.filter((other) => other.id !== item.id && (other.input === 0 || other.input === item.input) &&
    (field === "by" ? other.kind === "subject" : !["attribute", "aspect"].includes(other.kind)));
}

export function setLinks(intent, id, field, ids) {
  return update(intent, id, { [field]: ids });
}

export function setRelationEnd(intent, relationId, end, elementId) {
  return { ...intent, relations: intent.relations.map((relation) => relation.id === relationId ? { ...relation, [end]: elementId } : relation) };
}

export function dismissNote(intent, index) {
  return { ...intent, unresolved: intent.unresolved.filter((_note, position) => position !== index) };
}
