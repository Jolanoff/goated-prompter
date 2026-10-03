/** Human-readable debug labels; enum validation remains the backend's responsibility. */
export function geometryRows(geometry = {}) {
  return Object.entries(geometry).map(([key, value]) => ({
    label: key.replaceAll("_", " "),
    value: Array.isArray(value) ? value.join(", ") : String(value).replaceAll("_", " "),
  }));
}
