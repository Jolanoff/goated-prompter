// Visual Direction settings for the next Dataset run (vocabulary/visual.py validates the same shape).
// Each dimension can be turned off; its variation says how many directions take turns across the images.
// What the brief itself says about camera or light always wins on the server; these settings only shape what is left open.

export const VISUAL_DIMENSIONS = [
  ["framing", "Framing", "How much of the subjects and their surroundings each image shows."],
  ["camera_angle", "Camera angle", "Where each image is seen from."],
  ["composition", "Composition", "How the subjects sit within the frame."],
  ["lighting", "Lighting", "Where the light comes from and its quality."],
  ["atmosphere", "Atmosphere", "Haze, focus, reflections and shadows."],
];

export const VISUAL_VARIATIONS = [
  ["auto", "Auto (follows Creativity)"],
  ["same", "Same for every image"],
  ["low", "Two take turns"],
  ["medium", "Four take turns"],
  ["high", "As many as fit"],
];

export const VISUAL_KEY = "goated-prompter.dataset-visual-direction.v1";
const variations = new Set(VISUAL_VARIATIONS.map(([value]) => value));

export function defaultVisualDirection() {
  return Object.fromEntries(VISUAL_DIMENSIONS.map(([id]) => [id, { enabled: true, variation: "auto" }]));
}

/** Any stored or partial value as a complete, valid settings object; unknown fields are dropped. */
export function normalizeVisualDirection(value) {
  const settings = defaultVisualDirection();
  for (const [id] of VISUAL_DIMENSIONS) {
    const item = value?.[id];
    if (!item || typeof item !== "object") continue;
    if (typeof item.enabled === "boolean") settings[id].enabled = item.enabled;
    if (variations.has(item.variation)) settings[id].variation = item.variation;
  }
  return settings;
}

export function updateVisualDirection(settings, id, patch) {
  return normalizeVisualDirection({ ...settings, [id]: { ...settings[id], ...patch } });
}

export function readStoredVisual(storage = globalThis.localStorage) {
  try {
    const value = JSON.parse(storage?.getItem(VISUAL_KEY) || "null");
    return value && typeof value === "object" ? normalizeVisualDirection(value) : null;
  } catch { return null; }
}

export function writeStoredVisual(settings, storage = globalThis.localStorage) {
  try { storage?.setItem(VISUAL_KEY, JSON.stringify(normalizeVisualDirection(settings))); } catch { /* per-browser convenience only */ }
}

/** One line for the review dialog: which dimensions Visual Direction may fill, and how they vary. */
export function visualDirectionSummary(settings) {
  const on = VISUAL_DIMENSIONS.filter(([id]) => settings?.[id]?.enabled);
  if (!on.length) return "Off";
  return on.map(([id, label]) => {
    const variation = settings[id].variation;
    return variation === "auto" ? label : `${label} (${VISUAL_VARIATIONS.find(([value]) => value === variation)[1].toLowerCase()})`;
  }).join(", ");
}
