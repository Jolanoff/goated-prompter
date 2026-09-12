export const SAVED_KEY = "goated-prompter.saved-prompts.v1";
export const JOB_KEY = "goated-prompter.active-job";
export const referenceAttributes = [
  "subject",
  "face",
  "outfit",
  "pose",
  "composition",
  "camera",
  "scene",
  "lighting",
  "colors",
  "mood",
  "materials",
];
export const referenceSources = [
  "Off",
  "Image 1",
  "Image 2",
  "Image 3",
  "Image 4",
  "Blend",
];
const builderKeys = [
  "idea",
  "mode",
  "target_model",
  "creativity",
  "prompt_length",
  "director_preset",
  "custom_instructions",
  "generated_prompt",
  "lock_generated_prompt",
  ...referenceAttributes.map((key) => `reference_${key}_source`),
];

export function builderSnapshot(settings) {
  return Object.fromEntries(
    builderKeys
      .filter((key) => Object.hasOwn(settings, key))
      .map((key) => [
        key,
        key === "prompt_length" && settings[key] === "Maximum"
          ? "Maximum Detail"
          : settings[key],
      ]),
  );
}

export function hydrateBuilder(inputs, saved = {}, library) {
  const result = builderSnapshot({
    ...inputDefaults(inputs),
    ...Object.fromEntries(
      referenceAttributes.map((key) => [`reference_${key}_source`, "Off"]),
    ),
    ...builderSnapshot(saved),
  });
  if (library) {
    const find = (value) =>
      library.presets.find((item) => item.id === value || item.label === value);
    result.director_preset =
      (
        find(result.director_preset) ||
        find(library.default) ||
        library.presets[0]
      )?.id || "";
  }
  return result;
}

// Only one write may be in flight. Responses acknowledge versions, never restore inputs.
export function createBuilderSaver(write, onStatus, delay = 300) {
  let latest, saved, pending, timer;
  async function flush(keepalive = false) {
    clearTimeout(timer);
    if (pending) {
      await pending;
      return flush(keepalive);
    }
    if (latest === undefined) return;
    if (latest === saved) {
      onStatus("Saved", "");
      return;
    }
    const snapshot = latest;
    onStatus("Saving", "");
    pending = write(JSON.parse(snapshot), keepalive);
    try {
      await pending;
      saved = snapshot;
    } catch (error) {
      clearTimeout(timer);
      onStatus("Save failed", error.message);
      throw error;
    } finally {
      pending = null;
    }
    if (latest !== saved) return flush(keepalive);
    onStatus("Saved", "");
  }
  return {
    hydrate(snapshot) {
      latest = saved = JSON.stringify(snapshot);
      onStatus("Saved", "");
    },
    stage(snapshot) {
      const next = JSON.stringify(snapshot);
      if (next === latest) return;
      latest = next;
      clearTimeout(timer);
      onStatus("Saving", "");
      timer = setTimeout(() => flush().catch(() => {}), delay);
    },
    flush,
    dispose() {
      clearTimeout(timer);
    },
  };
}

export function loadSaved(storage) {
  const raw = storage.getItem(SAVED_KEY);
  if (!raw) return [];
  const records = JSON.parse(raw);
  if (
    !Array.isArray(records) ||
    records.some(
      (item) =>
        !item ||
        typeof item.id !== "string" ||
        typeof item.title !== "string" ||
        typeof item.prompt !== "string" ||
        typeof item.createdAt !== "string",
    )
  ) {
    throw new Error(
      "Saved prompts could not be read. Existing browser data has not been overwritten.",
    );
  }
  return records;
}

export function inputDefaults(inputs) {
  return Object.fromEntries(
    Object.entries(inputs).map(([key, [type, options]]) => [
      key,
      options?.default ?? (Array.isArray(type) ? type[0] : ""),
    ]),
  );
}
