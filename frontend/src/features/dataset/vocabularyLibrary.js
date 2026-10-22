export function sortPacks(packs, sort = "name") {
  const byName = (a, b) => a.name.localeCompare(b.name) || a.id.localeCompare(b.id);
  return [...packs].sort((a, b) => {
    if (sort === "entries") return b.entries.length - a.entries.length || byName(a, b);
    if (sort === "category") return a.category.localeCompare(b.category) || byName(a, b);
    return byName(a, b);
  });
}
