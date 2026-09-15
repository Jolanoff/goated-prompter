export const defaultResolution = () => ({ aspect_ratio: "Auto", width: 1024, height: 1024 });

export function resolutionError(value, catalog) {
  if (!value || value.aspect_ratio !== "Custom") return "";
  const min = catalog?.min ?? 16, max = catalog?.max ?? 16384;
  return [value.width, value.height].every((size) => Number.isInteger(size) && size >= min && size <= max)
    ? "" : `Enter a whole width and height between ${min} and ${max} pixels.`;
}

export function resolutionLabel(value) {
  return !value || value.aspect_ratio === "Auto" ? "Automatic framing" : `${value.width} × ${value.height} · ${value.aspect_ratio}`;
}
