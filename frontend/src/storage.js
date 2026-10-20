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
  "style",
  "capture",
  "planning_mode",
  "prompt_length",
  "director_preset",
  "custom_instructions",
  "generated_prompt",
  ...referenceAttributes.map((key) => `reference_${key}_source`),
];

export function builderSnapshot(settings) {
  return Object.fromEntries(
    builderKeys
      .filter((key) => Object.hasOwn(settings, key))
      .map((key) => [
        key,
        key === "planning_mode"
          ? "Direct"
          : key === "prompt_length" && settings[key] === "Maximum"
            ? "Maximum Detail"
            : settings[key],
      ]),
  );
}

const replacedDirectors = Object.fromEntries(Object.entries({
  photography_director: ["Realistic", "Pro camera"],
  smartphone_realism: ["Realistic", "Phone snapshot"],
  krea_2_smartphone_realism: ["Realistic", "Phone snapshot"],
  vintage_analog: ["Realistic", "Analog film"],
  anime_director: ["Anime", "Auto"],
}).flatMap(([id, value]) => [[id, value], [{
  photography_director: "Photography Director", smartphone_realism: "Smartphone Realism",
  krea_2_smartphone_realism: "Krea 2 Smartphone Realism", vintage_analog: "Vintage / Analog",
  anime_director: "Anime Director",
}[id], value]]));

// Director names saved before they were renamed.
const directorAliases = {
  "Maximum Detail Director": "maximum_detail_director",
  "Technical Visual Precision": "maximum_detail_director",
  "Krea 2 High Detail": "krea_2_high_detail",
  "Krea 2 Visual Precision": "krea_2_high_detail",
  "Krea 2 Identity Edit": "krea_2_identity_edit",
  "minimax_h3_director": "minimax_director",
  "MiniMax Director": "minimax_director",
  "MiniMax H3 Director": "minimax_director",
  "General Director": "general_director",
  "Prompt Enhancer": "prompt_enhancer",
  "Reverse Engineer": "reverse_engineer",
  "Surgical Edit": "surgical_edit",
  "Face Identity Analyst": "face_identity_analyst",
  "Subject Appearance Analyst": "subject_appearance_analyst",
  "Reference Composer": "reference_composer",
  "Arm's-Length Selfie": "arms_length_selfie",
  "First-Person POV": "first_person_pov",
  "Fashion Editorial": "fashion_editorial",
  "Boudoir / Intimate": "boudoir_intimate",
  "Krea 2 Pose Lock": "krea_2_pose_lock",
  "Video Director": "video_director",
  "Archviz Director": "archviz_director",
  "Character Director": "character_director",
  "Product Director": "product_director",
  "Style Transfer Director": "style_transfer_director",
  "Dataset Caption Director": "dataset_caption_director",
  "NSFW Director": "nsfw_director",
};

export function hydrateBuilder(inputs, saved = {}, library) {
  const result = builderSnapshot({
    planning_mode: "Direct",
    ...inputDefaults(inputs),
    ...Object.fromEntries(
      referenceAttributes.map((key) => [`reference_${key}_source`, "Off"]),
    ),
    ...builderSnapshot(saved),
  });
  const targetAliases = {
    "Z-Image Base": "Z-Image", "Z-Image Turbo": "Z-Image", "Qwen Image": "Qwen Image (original)",
    "Qwen2.1": "Qwen Image 2.1", "MiniMax": "MiniMax H3",
  };
  result.target_model = targetAliases[result.target_model] ?? result.target_model;
  // Directors that set a medium became Style choices: General plus that style and capture.
  const replaced = replacedDirectors[result.director_preset];
  if (replaced) {
    result.director_preset = "general_director";
    if ((result.style ?? "Auto") === "Auto") [result.style, result.capture] = replaced;
  }
  if (library) {
    result.director_preset = directorAliases[result.director_preset] ?? result.director_preset;
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
    async discard() {
      clearTimeout(timer);
      latest = undefined;
      if (pending) {
        try { await pending; } catch { /* The caller is explicitly reloading saved state. */ }
      }
    },
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
