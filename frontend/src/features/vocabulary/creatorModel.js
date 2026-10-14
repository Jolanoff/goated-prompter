export const fieldLabel = (key) => ({ id: "ID", requires: "Dependencies", extends: "Inherits from", any_of: "Any of",
  all_of: "All of", none_of: "None of", complete_for: "Complete for", claims: "Resource usage" }[key] ||
  key.replaceAll("_", " ").replace(/^./, (letter) => letter.toUpperCase()));

export function resolveSchema(schema, root) {
  return schema?.$ref ? resolveSchema(schema.$ref.split("/").slice(1).reduce((node, key) => node[key], root), root) : schema || {};
}

export function schemaDefault(source, root) {
  const schema = resolveSchema(source, root);
  if (schema.const !== undefined) return schema.const;
  if (schema.enum) return schema.enum[0];
  if (schema.oneOf) return schemaDefault(schema.oneOf[0], root);
  if (schema.type === "object") return Object.fromEntries((schema.required || []).map((key) => [key, schemaDefault(schema.properties[key], root)]));
  if (schema.type === "array") return [];
  if (schema.type === "integer") return schema.minimum || 0;
  return "";
}

export function variantIndex(schema, value, root) {
  return Math.max(0, schema.oneOf.findIndex((candidate) => {
    const part = resolveSchema(candidate, root);
    return part.type === "array" ? Array.isArray(value) : part.type === "object" ? value && typeof value === "object" && !Array.isArray(value)
      && (part.required || []).every((key) => Object.hasOwn(value, key)) : part.type === "integer" ? Number.isInteger(value) : typeof value === "string";
  }));
}

export const newPackDocument = () => ({ manifest: { spec: 1, id: "my_pack", name: "Untitled pack", version: "1.0.0", rating: "general",
  requires: { core: ">=1.0.0" }, files: ["entries.json"] }, files: { "entries.json": { spec: 1, entries: [] } }, extras: {} });

export function uniqueEntryId(document, base = "entry") {
  const prefix = document.manifest.id;
  const stem = base.includes(":") ? base.split(":")[1] : base;
  const ids = new Set(Object.values(document.files).flatMap((file) => (file.entries || []).map((entry) => entry.id)));
  let candidate = `${prefix}:${stem}`, index = 2;
  while (ids.has(candidate)) candidate = `${prefix}:${stem}_${index++}`;
  return candidate;
}

export function pathMatches(issue, path) {
  return path.length <= issue.path.length && path.every((key, index) => key === issue.path[index]);
}

export function replaceKey(object, previous, next) {
  if (!next || (next !== previous && Object.hasOwn(object, next))) return object;
  return Object.fromEntries(Object.entries(object).map(([key, value]) => [key === previous ? next : key, value]));
}

export function moveEntry(document, file, index, destination) {
  const next = structuredClone(document);
  const [entry] = next.files[file].entries.splice(index, 1);
  next.files[destination].entries.push(entry);
  return next;
}
