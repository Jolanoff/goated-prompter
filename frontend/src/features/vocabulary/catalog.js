// The Vocabulary catalog (GET /vocabulary/catalog) and the Dataset's selection of it, as plain data.
// A selection is a list of pack ids (the Dataset draft's vocabulary_packs); the server checks it again on Confirm.

/** The selected ids the catalog still has, in the order chosen, without repeats. */
export function cleanSelection(catalog, ids) {
  const known = new Set((catalog?.packs || []).map((pack) => pack.id));
  return [...new Set((ids || []).filter((id) => known.has(id)))];
}

export function togglePack(ids, id) {
  return ids.includes(id) ? ids.filter((item) => item !== id) : [...ids, id];
}

/** [{ category, packs }] in registry order; every category is listed, with or without packs. */
export function packsByCategory(catalog) {
  return (catalog?.categories || []).map((category) => ({
    category, packs: (catalog.packs || []).filter((pack) => pack.category === category.id) }));
}

/** The packs a search and category filter show: the query matches a pack's name, category, description or any entry. */
export function filterPacks(catalog, query = "", category = "") {
  const words = query.trim().toLowerCase();
  return (catalog?.packs || []).filter((pack) => (!category || pack.category === category) && (!words
    || [pack.name, pack.category, pack.description || "", ...pack.entries].some((text) => text.toLowerCase().includes(words))));
}

/** The packs that work with a pack through slots: the ones its entries name in [brackets] ("uses") and the ones whose
 * entries name it ("usedBy"). The server lists each pack's slots as links: [{ slot, packs: [ids] }]. */
export function linkedPacks(catalog, id) {
  const packs = catalog?.packs || [];
  const byId = new Map(packs.map((pack) => [pack.id, pack]));
  const uses = [...new Set((byId.get(id)?.links || []).flatMap((link) => link.packs))].map((ident) => byId.get(ident))
    .filter(Boolean);
  const usedBy = packs.filter((pack) => pack.id !== id && (pack.links || []).some((link) => link.packs.includes(id)));
  return { uses, usedBy };
}

/** The slots of the chosen packs that no chosen pack fills: [{ pack, slot, options }]. A run skips the entries that
 * hold them until one of the options is chosen. */
export function missingLinks(catalog, ids) {
  const chosen = new Set(ids || []);
  const byId = new Map((catalog?.packs || []).map((pack) => [pack.id, pack]));
  return (ids || []).flatMap((id) => (byId.get(id)?.links || [])
    .filter((link) => !link.packs.some((ident) => chosen.has(ident)))
    .map((link) => ({ pack: byId.get(id), slot: link.slot,
      options: link.packs.map((ident) => byId.get(ident)).filter(Boolean) })));
}

/** The names of the selected packs, for "Selected: Fantasy, Cinematic". */
export function selectedNames(catalog, ids) {
  const packs = new Map((catalog?.packs || []).map((pack) => [pack.id, pack]));
  return (ids || []).map((id) => packs.get(id)?.name || id);
}

/** A run's recorded selection ({ packs: [{ id, name, category, entries }] }) as "Name (Category)" labels. */
export function recordedNames(recorded) {
  return (recorded?.packs || []).map((pack) => `${pack.name} (${pack.category})`);
}
