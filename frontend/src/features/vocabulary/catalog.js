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

/** The packs a search and category filter show: the query matches a pack's name, its category or any entry. */
export function filterPacks(catalog, query = "", category = "") {
  const words = query.trim().toLowerCase();
  return (catalog?.packs || []).filter((pack) => (!category || pack.category === category) && (!words
    || [pack.name, pack.category, ...pack.entries].some((text) => text.toLowerCase().includes(words))));
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
