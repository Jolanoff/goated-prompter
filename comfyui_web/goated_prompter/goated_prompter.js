import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";
import {
  DEFAULT_ACCENT,
  SWATCHES,
  THEMES,
  THEME_TOKENS,
  activeFill,
  activeForeground,
  buildAccentPalette,
  drawPaletteIcon,
  drawRound,
  drawText,
  ellipsize,
  hexToRgba,
  normalizeHex,
} from "../shared/ui_shared.js";

const NODE_NAME = "GoatedPrompter";
const ROUTE = "/goated-prompter/v1/generate";
const TEXT_ROUTE = "/goated-prompter/v1/generate-text";
const MODELS_ROUTE = "/goated-prompter/v1/models";
const PRESETS_ROUTE = "/goated-prompter/v1/presets";
const UNLOAD_ROUTE = "/goated-prompter/v1/unload";
const MODES = ["Enhance", "Archviz", "Photography", "Character", "Product", "Image Edit", "Style Transfer", "Dataset Caption", "Video", "Custom"];
const TARGETS = ["Generic", "Krea 2", "FLUX.2 Klein", "Z-Image", "Qwen Image", "MiniMax", "LTX 2.5", "Ideogram4"];
const CREATIVITY = ["Strict", "Balanced", "Creative", "Dice"];
const PROMPT_MODELS = ["Qwen 3.5 9B", "Qwen 3.5 9B — Uncensored", "Qwen 3.5 9B — HauhauCS Aggressive", "Gemma 3 12B", "Custom"];
const DIRECTOR_PRESETS = [
  "General Director", "Prompt Enhancer", "Reverse Engineer", "Surgical Edit",
  "Face Identity Analyst", "Subject Appearance Analyst", "Reference Composer",
  "Photography Director", "Smartphone Realism", "Arm's-Length Selfie", "Mirror Selfie",
  "First-Person POV", "Fashion Editorial", "Vintage / Analog", "Boudoir / Intimate",
  "Krea 2 High Detail", "Krea 2 Smartphone Realism", "Krea 2 Pose Lock",
  "Video Director", "MiniMax H3 Director", "Archviz Director", "Character Director",
  "Product Director", "Style Transfer Director", "Dataset Caption Director",
  "Maximum Detail Director",
];
const DEFAULT_DIRECTOR_PRESET = "General Director";
const WORKFLOW_RULES_HELP = "Extra rules applied to this specific workflow.";
const WORKFLOW_RULES_PLACEHOLDER = "Example: Always preserve the original pose and camera angle. Keep prompts under 150 words.";
const DIRECTOR_BEHAVIOR_HELP = "Defines how this reusable Director analyzes and writes prompts.";
const DIRECTOR_BEHAVIOR_PLACEHOLDER = "Example: You are an expert visual reverse engineer. Analyze pose, composition, camera, lighting and materials precisely. Preserve visible evidence and avoid invented details.";
const MODE_DIRECTORS = {
  Enhance: "General Director",
  Photography: "Photography Director",
  Archviz: "Archviz Director",
  Video: "Video Director",
  Product: "Product Director",
  Character: "Character Director",
  "Image Edit": "Surgical Edit",
  "Style Transfer": "Style Transfer Director",
  "Dataset Caption": "Dataset Caption Director",
  Custom: "General Director",
};
const LENGTHS = ["Short", "Medium", "Detailed", "Maximum Detail"];
const REFERENCE_SOURCES = ["Auto", "Image 1", "Image 2", "Blend", "Off", "Image 3", "Image 4"];
const REFERENCE_SOURCE_LABELS = {
  Auto: "AUTO", "Image 1": "IMG 1", "Image 2": "IMG 2", "Image 3": "IMG 3",
  "Image 4": "IMG 4", Blend: "BLEND", Off: "OFF",
};
const REFERENCE_MAP_FIELDS = [
  ["reference_subject_source", "Subject"], ["reference_face_source", "Face / Identity"],
  ["reference_outfit_source", "Outfit"], ["reference_pose_source", "Pose"],
  ["reference_composition_source", "Composition"], ["reference_camera_source", "Camera"],
  ["reference_scene_source", "Scene / Env."], ["reference_lighting_source", "Lighting"],
  ["reference_colors_source", "Colors"], ["reference_mood_source", "Mood / Style"],
  ["reference_materials_source", "Materials"],
];
const WIDGET_NAMES = [
  "idea", "mode", "target_model", "creativity",
  "preserve_subject", "preserve_composition", "preserve_camera",
  "preserve_materials", "preserve_lighting", "preserve_colors",
  "prompt_length", "custom_instructions", "system_prompt_override", "generated_prompt",
  "prompt_model", "director_profile", "director_model_path", "director_mmproj_path",
  "director_llama_server", "director_context_size", "director_image_min_tokens",
  "director_max_tokens", "director_gpu_layers", "director_keep_model_loaded",
  "director_preset", "image_1_role", "image_2_role",
  ...REFERENCE_MAP_FIELDS.map(([field]) => field),
];
const PRESERVE_FIELDS = [
  ["preserve_subject", "Subject"], ["preserve_composition", "Composition"],
  ["preserve_camera", "Camera"], ["preserve_materials", "Materials"],
  ["preserve_lighting", "Lighting"], ["preserve_colors", "Colors"],
];

function ensureProperties(node) {
  node.properties = node.properties || {};
  if (typeof node.properties.goatedPrompterAdvancedOpen !== "boolean") {
    node.properties.goatedPrompterAdvancedOpen = false;
  }
  if (typeof node.properties.goatedPrompterAppearanceOpen !== "boolean") {
    node.properties.goatedPrompterAppearanceOpen = false;
  }
  node.properties.goatedPrompterTheme = THEMES.includes(node.properties.goatedPrompterTheme)
    ? node.properties.goatedPrompterTheme : "Dark";
  node.properties.goatedPrompterAccent = normalizeHex(node.properties.goatedPrompterAccent) || DEFAULT_ACCENT;
  node.properties.goatedPrompterContrast = Boolean(node.properties.goatedPrompterContrast);
  node._goatedPrompterStatus = node._goatedPrompterStatus || { kind: "idle", message: "Ready" };
}

function hideWidget(item) {
  if (!item) return;
  item.hidden = true;
  item.options = item.options || {};
  item.options.hidden = true;
  if (!item.type?.startsWith("converted-widget")) {
    item.computeSize = () => [0, 0];
    item.draw = () => {};
  }
  if (item.element) item.element.style.display = "none";
  if (item.inputEl) item.inputEl.style.display = "none";
}

function detachWidgets(node, values) {
  const found = new Map();
  for (const item of [...(node.widgets || []), ...(node._goatedPrompterWidgets || [])]) {
    if (item?.name && WIDGET_NAMES.includes(item.name) && !found.has(item.name)) found.set(item.name, item);
  }
  node._goatedPrompterWidgets = WIDGET_NAMES.map((name) => found.get(name)).filter(Boolean);
  node._goatedPrompterWidgetMap = found;
  if (Array.isArray(values)) {
    WIDGET_NAMES.forEach((name, index) => {
      const item = found.get(name);
      if (item && values[index] !== undefined) item.value = values[index];
    });
  }
  node._goatedPrompterWidgets.forEach(hideWidget);
  const promptModel = found.get("prompt_model");
  if (promptModel) promptModel.value = normalizePromptModel(promptModel.value);
  const promptLength = found.get("prompt_length");
  if (promptLength) promptLength.value = normalizePromptLength(promptLength.value);
  const directorPreset = found.get("director_preset");
  const directorPresetIndex = WIDGET_NAMES.indexOf("director_preset");
  if (directorPreset && Array.isArray(values) && values.length <= directorPresetIndex) {
    directorPreset.value = legacyPresetForMode(found.get("mode")?.value);
  } else if (directorPreset) {
    directorPreset.value = normalizeDirectorPreset(directorPreset.value);
  }
}

function legacyPresetForMode(mode) {
  return MODE_DIRECTORS[String(mode || "")] || DEFAULT_DIRECTOR_PRESET;
}

function normalizeDirectorPreset(value) {
  const raw = String(value || "").trim();
  const aliases = {
    "Reference Reconstruction": "Reverse Engineer",
    "Creative Enhancement": "General Director",
    "Archviz Reconstruction": "Archviz Director",
    "Image Edit Director": "Surgical Edit",
  };
  return aliases[raw] || raw || DEFAULT_DIRECTOR_PRESET;
}

function normalizePromptModel(value) {
  const compact = String(value || "").toLowerCase().replace(/[^a-z0-9]+/g, "");
  const aliases = {
    default: "Qwen 3.5 9B",
    qwen359b: "Qwen 3.5 9B",
    qwen359bstandard: "Qwen 3.5 9B",
    uncensored: "Qwen 3.5 9B — Uncensored",
    qwen359buncensored: "Qwen 3.5 9B — Uncensored",
    qwen359buncensoredhauhaucsaggressive: "Qwen 3.5 9B — HauhauCS Aggressive",
    qwen359bhauhaucsaggressive: "Qwen 3.5 9B — HauhauCS Aggressive",
    gemma: "Gemma 3 12B",
    gemma312b: "Gemma 3 12B",
    custom: "Custom",
  };
  return aliases[compact] || "Qwen 3.5 9B";
}

function widget(node, name) {
  return node._goatedPrompterWidgetMap?.get(name) || (node.widgets || []).find((item) => item?.name === name);
}

function value(node, name, fallback = "") {
  const item = widget(node, name);
  return item ? item.value : fallback;
}

function setStatus(node, kind, message) {
  node._goatedPrompterStatus = { kind, message };
  node.setDirtyCanvas(true, true);
}

function setValue(node, name, next, invalidate = true) {
  const item = widget(node, name);
  if (!item || Object.is(item.value, next)) return false;
  item.value = next;
  node._goatedPrompterRevision = {};
  if (invalidate && name !== "generated_prompt") {
    const generated = widget(node, "generated_prompt");
    if (generated) generated.value = "";
    setStatus(node, "idle", "Settings changed — generate again");
  }
  node.setDirtyCanvas(true, true);
  return true;
}

function promptFromExecution(message) {
  const payload = message?.generated_prompt;
  const prompt = Array.isArray(payload) ? payload[0] : payload;
  return typeof prompt === "string" ? prompt : null;
}

function normalizePromptLength(value) {
  const raw = String(value || "").trim();
  return raw === "Maximum" ? "Maximum Detail" : (LENGTHS.includes(raw) ? raw : "Medium");
}

function showCopyFeedback(node, label, kind, message) {
  const until = Date.now() + 1400;
  node._goatedPrompterCopyFeedback = { label, until };
  setStatus(node, kind, message);
  globalThis.setTimeout?.(() => {
    if (node._goatedPrompterCopyFeedback?.until !== until) return;
    delete node._goatedPrompterCopyFeedback;
    node.setDirtyCanvas(true, true);
  }, 1450);
}

async function copyGeneratedPrompt(node) {
  const prompt = String(value(node, "generated_prompt", ""));
  if (!prompt.trim()) {
    showCopyFeedback(node, "EMPTY", "idle", "Generated prompt is empty");
    return;
  }

  let copied = false;
  try {
    if (globalThis.navigator?.clipboard?.writeText) {
      await globalThis.navigator.clipboard.writeText(prompt);
      copied = true;
    }
  } catch {
    copied = false;
  }

  if (!copied) {
    let area = null;
    try {
      area = document.createElement("textarea");
      area.value = prompt;
      area.setAttribute("readonly", "");
      area.style.cssText = "position:fixed;left:-9999px;top:0;opacity:0;";
      document.body.appendChild(area);
      area.select();
      copied = document.execCommand("copy");
    } catch {
      copied = false;
    } finally {
      area?.remove();
    }
  }

  showCopyFeedback(
    node,
    copied ? "COPIED!" : "FAILED",
    copied ? "success" : "error",
    copied ? "Generated prompt copied" : "Could not copy generated prompt",
  );
}

function state(node) {
  const current = {
    idea: String(value(node, "idea", "")),
    mode: String(value(node, "mode", "Enhance")),
    target_model: String(value(node, "target_model", "Generic")),
    creativity: String(value(node, "creativity", "Balanced")),
    prompt_model: normalizePromptModel(value(node, "prompt_model", "Qwen 3.5 9B")),
    director_preset: String(value(node, "director_preset", DEFAULT_DIRECTOR_PRESET)),
    director_profile: String(value(node, "director_profile", "")),
    director_model_path: String(value(node, "director_model_path", "")),
    director_mmproj_path: String(value(node, "director_mmproj_path", "")),
    director_llama_server: String(value(node, "director_llama_server", "")),
    director_context_size: Number(value(node, "director_context_size", 8192)),
    director_image_min_tokens: Number(value(node, "director_image_min_tokens", 1024)),
    director_max_tokens: Number(value(node, "director_max_tokens", 768)),
    director_gpu_layers: String(value(node, "director_gpu_layers", "auto")),
    preserve_subject: Boolean(value(node, "preserve_subject", true)),
    preserve_composition: Boolean(value(node, "preserve_composition", false)),
    preserve_camera: Boolean(value(node, "preserve_camera", false)),
    preserve_materials: Boolean(value(node, "preserve_materials", false)),
    preserve_lighting: Boolean(value(node, "preserve_lighting", false)),
    preserve_colors: Boolean(value(node, "preserve_colors", false)),
    prompt_length: normalizePromptLength(value(node, "prompt_length", "Medium")),
    custom_instructions: String(value(node, "custom_instructions", "")),
    system_prompt_override: String(value(node, "system_prompt_override", "")),
    generated_prompt: String(value(node, "generated_prompt", "")),
    image_1_role: String(value(node, "image_1_role", "Auto")),
    image_2_role: String(value(node, "image_2_role", "Auto")),
  };
  REFERENCE_MAP_FIELDS.forEach(([field]) => { current[field] = String(value(node, field, "Auto")); });
  return current;
}

function textOnlyPayload(current) {
  return {
    idea: current.idea,
    mode: current.mode,
    target_model: current.target_model,
    creativity: current.creativity,
    prompt_model: current.prompt_model,
    director_preset: current.director_preset,
    director_profile: current.director_profile,
    director_model_path: current.director_model_path,
    director_mmproj_path: current.director_mmproj_path,
    director_llama_server: current.director_llama_server,
    director_context_size: current.director_context_size,
    director_image_min_tokens: current.director_image_min_tokens,
    director_max_tokens: current.director_max_tokens,
    director_gpu_layers: current.director_gpu_layers,
    prompt_length: current.prompt_length,
    custom_instructions: current.custom_instructions,
    system_prompt_override: current.system_prompt_override,
  };
}

function directorProfiles(node) {
  return Array.isArray(node._goatedPrompterDiscovery?.profiles)
    ? node._goatedPrompterDiscovery.profiles : [];
}

function directorPresets(node) {
  return Array.isArray(node._goatedPrompterPresets?.presets)
    ? node._goatedPrompterPresets.presets : [];
}

function activeDirectorPreset(node, directorState = state(node)) {
  return directorPresets(node).find((item) => item.label === directorState.director_preset) || null;
}

function promptModelOptions(node) {
  const discovered = directorProfiles(node)
    .filter((profile) => profile.vision_ready && profile.prompt_model && profile.prompt_model !== "Custom")
    .map((profile) => profile.prompt_model);
  if (!discovered.length) return PROMPT_MODELS;
  const current = normalizePromptModel(value(node, "prompt_model", PROMPT_MODELS[0]));
  return [...new Set([...discovered, current, "Custom"])];
}

function directorPresetOptions(node) {
  const discovered = directorPresets(node).map((preset) => preset.label).filter(Boolean);
  return discovered.length ? discovered : DIRECTOR_PRESETS;
}

function directorWarning(node, directorState) {
  const discovery = node._goatedPrompterDiscovery;
  if (!discovery) return "";
  const selected = directorState.prompt_model === "Custom"
    ? directorProfiles(node).find((item) => item.id === directorState.director_profile)
    : discovery.assignments?.[directorState.prompt_model];
  if (selected?.warning) return selected.warning;
  const warnings = Array.isArray(discovery.warnings) ? discovery.warnings.filter(Boolean) : [];
  if (!warnings.length) return "";
  return `${warnings[0]}${warnings.length > 1 ? ` (+${warnings.length - 1} more)` : ""}`;
}

function directorHint(node, directorState) {
  if (node._goatedPrompterModelsLoading) return "Scanning local models...";
  if (node._goatedPrompterModelsError) return "Model scan unavailable — Refresh in Advanced";
  const discovery = node._goatedPrompterDiscovery;
  if (!discovery) return "Local profile status unavailable";
  const backend = String(discovery.backend || "auto").toLowerCase().replaceAll("-", "_");
  if (["mock", "debug", "openai", "openai_compatible"].includes(backend)) return "Uses configured backend";
  if (directorState.prompt_model === "Custom") {
    const profile = directorProfiles(node).find((item) => item.id === directorState.director_profile);
    if (!profile) return "Choose a discovered profile in Advanced";
    if (!profile.vision_ready) return `${profile.label} — incomplete`;
    return `${profile.label}${profile.warning ? " ⚠" : ""}`;
  }
  const assigned = discovery.assignments?.[directorState.prompt_model];
  return assigned ? `${assigned.folder}${assigned.warning ? " ⚠" : ""}` : `${directorState.prompt_model} not installed`;
}

function presetHint(node, directorState) {
  if (node._goatedPrompterPresetsLoading) return "Loading preset definition...";
  if (node._goatedPrompterPresetsError) return "Director library unavailable";
  const preset = activeDirectorPreset(node, directorState);
  return preset?.description || "Preset controls prompt behavior independently from the model";
}

async function refreshDirectorProfiles(node, force = false) {
  if (node._goatedPrompterModelsLoading) return;
  node._goatedPrompterModelsLoading = true;
  node._goatedPrompterModelsError = "";
  node.setDirtyCanvas(true, true);
  try {
    const suffix = force ? "?refresh=1" : "";
    const response = await api.fetchApi(`${MODELS_ROUTE}${suffix}`);
    let data = {};
    try { data = await response.json(); } catch { data = {}; }
    if (!response.ok || !data.ok) throw new Error(data.error || `Model discovery failed (${response.status})`);
    node._goatedPrompterDiscovery = data;
  } catch (error) {
    node._goatedPrompterModelsError = error?.message || "Model discovery failed";
  } finally {
    node._goatedPrompterModelsLoading = false;
    node.setDirtyCanvas(true, true);
  }
}

async function refreshDirectorPresets(node, force = false) {
  if (node._goatedPrompterPresetsLoading) return;
  node._goatedPrompterPresetsLoading = true;
  node._goatedPrompterPresetsError = "";
  node.setDirtyCanvas(true, true);
  try {
    const suffix = force ? "?refresh=1" : "";
    const response = await api.fetchApi(`${PRESETS_ROUTE}${suffix}`);
    let data = {};
    try { data = await response.json(); } catch { data = {}; }
    if (!response.ok || !data.ok || !Array.isArray(data.presets)) throw new Error(data.error || `Preset loading failed (${response.status})`);
    node._goatedPrompterPresets = data;
  } catch (error) {
    node._goatedPrompterPresetsError = error?.message || "Preset loading failed";
  } finally {
    node._goatedPrompterPresetsLoading = false;
    node.setDirtyCanvas(true, true);
  }
}

function configureReferenceInputs(node) {
  const image1 = (node.inputs || []).find((item) => item?.name === "image");
  const image2 = (node.inputs || []).find((item) => item?.name === "image_2");
  if (image1) image1.label = "IMAGE 1";
  if (image2) image2.label = "IMAGE 2";
}

function connectedReferences(node) {
  return [
    ["image", "IMAGE 1", "image_1_role"],
    ["image_2", "IMAGE 2", "image_2_role"],
  ].filter(([name]) => (node.inputs || []).find((item) => item?.name === name)?.link != null);
}

function groundingLabel(node) {
  const references = connectedReferences(node);
  if (references.length === 2) return "2 REFERENCES GROUNDED AT QUEUE";
  return references.length === 1 ? `${references[0][1]} GROUNDED AT QUEUE` : "";
}

function wrapLines(ctx, text, maxWidth, maxLines) {
  const words = String(text || "").replace(/\s+/g, " ").trim().split(" ").filter(Boolean);
  const lines = [];
  let line = "";
  for (const word of words) {
    const candidate = line ? `${line} ${word}` : word;
    if (line && ctx.measureText(candidate).width > maxWidth) {
      lines.push(line);
      line = word;
      if (lines.length === maxLines) break;
    } else {
      line = candidate;
    }
  }
  if (line && lines.length < maxLines) lines.push(line);
  if (lines.length === maxLines && words.join(" ") !== lines.join(" ")) {
    lines[maxLines - 1] = ellipsize(ctx, `${lines[maxLines - 1]}...`, maxWidth);
  }
  return lines;
}

function drawParagraph(ctx, text, box, color, placeholder, tokens, maxLines = 4) {
  ctx.font = "500 13px system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif";
  const content = String(text || "").trim();
  const lines = wrapLines(ctx, content || placeholder, box.w - 24, maxLines);
  lines.forEach((line, index) => drawText(ctx, line, box.x + 12, box.y + 20 + index * 18, 13, content ? color : tokens.textMuted, "500"));
}

function nativeInputContentStart(node) {
  const nativeInputs = (node.inputs || []).filter((item) => !item?.widget);
  if (!nativeInputs.length) return 14;
  const slotHeight = Number(globalThis.LiteGraph?.NODE_SLOT_HEIGHT) || 20;
  const rowGap = 6;
  return 14 + nativeInputs.length * slotHeight + rowGap;
}

function makeLayout(node, current = state(node)) {
  const width = Math.max(400, node.size?.[0] || 460);
  const x = 14;
  const w = width - 28;
  let y = nativeInputContentStart(node);
  const gap = 10;
  const hits = [];
  const hit = (kind, box, field = null) => hits.push({ kind, field, ...box });

  const idea = { x, y, w, h: 96 }; hit("text", idea, "idea"); y += idea.h + gap;
  const selectGap = 7;
  const selectW = (w - selectGap * 2) / 3;
  const selectors = [
    { field: "mode", label: "MODE", options: MODES, x, y, w: selectW, h: 58 },
    { field: "target_model", label: "TARGET", options: TARGETS, x: x + selectW + selectGap, y, w: selectW, h: 58 },
    { field: "creativity", label: "CREATIVITY", options: CREATIVITY, x: x + (selectW + selectGap) * 2, y, w: selectW, h: 58 },
  ];
  selectors.forEach((box) => hit("choice", box, box.field)); y += 58 + gap;
  const promptModel = { field: "prompt_model", label: "PROMPT MODEL", options: PROMPT_MODELS, x, y, w, h: 58 };
  hit("choice", promptModel, "prompt_model"); y += promptModel.h + gap;
  const directorPreset = { field: "director_preset", label: "DIRECTOR PRESET", options: DIRECTOR_PRESETS, x, y, w, h: 58 };
  hit("choice", directorPreset, "director_preset"); y += directorPreset.h + gap;
  const generate = { x, y, w, h: 42 }; hit("generate", generate); y += 42 + gap;
  const output = { x, y, w, h: 126 };
  const copyGenerated = { x: x + w - 128, y: y + 103, w: 58, h: 20 };
  hit("copyGenerated", copyGenerated);
  hit("text", output, "generated_prompt");
  y += 126 + gap;

  const open = node.properties?.goatedPrompterAdvancedOpen === true;
  const customDirector = current.prompt_model === "Custom";
  const userDirector = activeDirectorPreset(node, current)?.source === "user";
  const connected = connectedReferences(node);
  const referenceMapRows = REFERENCE_MAP_FIELDS.length;
  const referenceMapHeight = connected.length ? 24 + referenceMapRows * 27 : 0;
  const advanced = { x, y, w, h: open ? (customDirector ? 428 : 364) + referenceMapHeight : 40 };
  hit("advanced", { x, y, w, h: 40 });
  const preserve = [];
  const referenceMap = [];
  let referenceMapHeader = null;
  let length = null;
  let custom = null;
  let system = null;
  let resetPreset = null;
  let saveAsDirector = null;
  let deleteDirector = null;
  let directorStatus = null;
  let unloadModel = null;
  let refreshModels = null;
  let customProfile = null;
  if (open) {
    const colW = (w - 28) / 3;
    PRESERVE_FIELDS.forEach(([field, label], index) => {
      const box = { field, label, x: x + 14 + (index % 3) * colW, y: y + 62 + Math.floor(index / 3) * 30, w: colW, h: 24 };
      preserve.push(box); hit("toggle", box, field);
    });
    let contentY = 130;
    if (connected.length) {
      referenceMapHeader = { x: x + 14, y: y + contentY, w: w - 28, h: 20 };
      const hasImage1 = connected.some(([name]) => name === "image");
      const hasImage2 = connected.some(([name]) => name === "image_2");
      const labelW = Math.min(112, Math.max(92, (w - 28) * 0.27));
      const segmentGap = 3;
      const selectorX = x + 14 + labelW + 7;
      const selectorW = w - 28 - labelW - 7;
      const segmentW = (selectorW - segmentGap * 3) / 4;
      REFERENCE_MAP_FIELDS.forEach(([field, label], index) => {
        const rowY = y + contentY + 22 + index * 27;
        const segments = REFERENCE_SOURCES.map((source, sourceIndex) => {
          const disabled = (source === "Image 1" && !hasImage1)
            || (source === "Image 2" && !hasImage2)
            || (source === "Blend" && !(hasImage1 && hasImage2));
          const segment = {
            field, value: source, disabled,
            x: selectorX + sourceIndex * (segmentW + segmentGap), y: rowY + 1, w: segmentW, h: 22,
          };
          hit("referenceSource", segment, field);
          return segment;
        });
        referenceMap.push({ field, label, x: x + 14, y: rowY, w: w - 28, h: 24, segments });
      });
      contentY += referenceMapHeight;
    }
    length = { x: x + 14, y: y + contentY, w: w - 28, h: 36, field: "prompt_length", label: "PROMPT LENGTH", options: LENGTHS };
    hit("choice", length, "prompt_length");
    custom = { x: x + 14, y: y + contentY + 46, w: w - 28, h: 52 }; hit("text", custom, "custom_instructions");
    const buttonGap = 6;
    const buttonWidths = userDirector ? [54, 58, 58] : [54, 58];
    const actionWidth = buttonWidths.reduce((total, width) => total + width, 0) + buttonGap * (buttonWidths.length - 1);
    let actionX = x + w - 14 - actionWidth;
    system = { x: x + 14, y: y + contentY + 118, w: actionX - (x + 14) - 8, h: 52 }; hit("text", system, "system_prompt_override");
    resetPreset = { x: actionX, y: y + contentY + 126, w: buttonWidths[0], h: 36 }; hit("resetPreset", resetPreset);
    actionX += buttonWidths[0] + buttonGap;
    saveAsDirector = { x: actionX, y: y + contentY + 126, w: buttonWidths[1], h: 36 }; hit("saveAsDirector", saveAsDirector);
    if (userDirector) {
      actionX += buttonWidths[1] + buttonGap;
      deleteDirector = { x: actionX, y: y + contentY + 126, w: buttonWidths[2], h: 36 }; hit("deleteDirector", deleteDirector);
    }
    directorStatus = { x: x + 14, y: y + contentY + 188, w: w - 234, h: 30 };
    unloadModel = { x: x + w - 212, y: y + contentY + 188, w: 112, h: 30 }; hit("unloadModel", unloadModel);
    refreshModels = { x: x + w - 94, y: y + contentY + 188, w: 80, h: 30 }; hit("refreshModels", refreshModels);
    if (customDirector) {
      customProfile = { field: "director_profile", label: "CUSTOM PROFILE", x: x + 14, y: y + contentY + 228, w: w - 28, h: 54 };
      hit("directorProfile", customProfile, "director_profile");
    }
  }
  y += advanced.h + 8;

  const appearanceOpen = node.properties?.goatedPrompterAppearanceOpen === true;
  const appearance = { x, y, w, h: appearanceOpen ? 150 : 40 };
  hit("appearance", { x, y, w, h: 40 });
  const themeButtons = [];
  const swatches = [];
  let contrast = null;
  let customAccent = null;
  let resetAccent = null;
  if (appearanceOpen) {
    const themeW = 58;
    THEMES.forEach((name, index) => {
      const box = { name, x: x + 78 + index * (themeW + 6), y: y + 42, w: themeW, h: 28 };
      themeButtons.push(box); hit("theme", box, name);
    });
    contrast = { x: x + w - 98, y: y + 42, w: 84, h: 28 }; hit("contrast", contrast);
    SWATCHES.forEach((color, index) => {
      const box = { color, x: x + 78 + index * 27, y: y + 84, w: 18, h: 18 };
      swatches.push(box); hit("accent", box, color);
    });
    customAccent = { x: x + 78, y: y + 116, w: 92, h: 20 }; hit("customAccent", customAccent);
    resetAccent = { x: x + 184, y: y + 116, w: 90, h: 20 }; hit("resetAccent", resetAccent);
  }
  y += appearance.h + 8;
  const footer = { x, y, w, h: 22 };
  const desiredHeight = footer.y + footer.h + 10;
  return { width, desiredHeight, hits, idea, selectors, promptModel, directorPreset, generate, output, copyGenerated, advanced, preserve, referenceMap, referenceMapHeader, length, custom, system, resetPreset, saveAsDirector, deleteDirector, directorStatus, unloadModel, refreshModels, customProfile, appearance, themeButtons, swatches, contrast, customAccent, resetAccent, footer };
}

function drawSelector(ctx, box, selected, tokens, accent) {
  drawText(ctx, box.label, box.x + 2, box.y + 11, 11, tokens.textMuted, "850");
  const field = { x: box.x, y: box.y + 22, w: box.w, h: 34 };
  drawRound(ctx, field, tokens.surface, tokens.border, 1, 6);
  drawText(ctx, ellipsize(ctx, selected, field.w - 30), field.x + 10, field.y + 17, 12, tokens.text, "700");
  drawText(ctx, "v", field.x + field.w - 14, field.y + 17, 12, accent, "900", "center");
}

function drawUI(node, ctx) {
  ensureProperties(node);
  const s = state(node);
  const t = THEME_TOKENS[node.properties.goatedPrompterTheme] || THEME_TOKENS.Dark;
  const accent = node.properties.goatedPrompterAccent;
  const palette = buildAccentPalette(accent, node.properties.goatedPrompterContrast);
  const l = makeLayout(node, s);
  node._goatedPrompterHits = l.hits;
  if (!node.size || node.size[0] !== l.width || Math.abs(node.size[1] - l.desiredHeight) > 2) node.size = [l.width, l.desiredHeight];

  drawRound(ctx, { x: 7, y: 7, w: l.width - 14, h: l.desiredHeight - 14 }, t.background, t.borderStrong, 1.5, 12);
  drawText(ctx, "WHAT DO YOU WANT?", l.idea.x + 2, l.idea.y + 11, 11, accent, "850");
  const grounding = groundingLabel(node);
  if (grounding) drawText(ctx, grounding, l.idea.x + l.idea.w - 2, l.idea.y + 11, 10, accent, "800", "right");
  const ideaBox = { x: l.idea.x, y: l.idea.y + 22, w: l.idea.w, h: 74 };
  drawRound(ctx, ideaBox, t.surface, t.border, 1, 7);
  drawParagraph(ctx, s.idea, ideaBox, t.text, "Describe the image or the change you want...", t, 3);
  drawText(ctx, "EDIT", ideaBox.x + ideaBox.w - 26, ideaBox.y + ideaBox.h - 11, 10, accent, "850", "center");

  l.selectors.forEach((box) => drawSelector(ctx, box, s[box.field], t, accent));
  drawSelector(ctx, l.promptModel, s.prompt_model, t, accent);
  drawText(ctx, ellipsize(ctx, directorHint(node, s), l.promptModel.w - 124), l.promptModel.x + l.promptModel.w - 2, l.promptModel.y + 11, 10, t.textMuted, "650", "right");
  drawSelector(ctx, l.directorPreset, s.director_preset, t, accent);
  drawText(ctx, ellipsize(ctx, presetHint(node, s), l.directorPreset.w - 140), l.directorPreset.x + l.directorPreset.w - 2, l.directorPreset.y + 11, 10, t.textMuted, "650", "right");
  const busy = node._goatedPrompterInFlight;
  drawRound(ctx, l.generate, busy ? t.surfaceRaised : activeFill(palette, 0.9), accent, 1.5, 7);
  drawText(ctx, busy ? "GENERATING..." : "GENERATE", l.generate.x + l.generate.w / 2, l.generate.y + 21, 14, busy ? t.textMuted : activeForeground(palette, t.text), "900", "center");

  drawText(ctx, "GENERATED PROMPT", l.output.x + 2, l.output.y + 11, 11, t.textMuted, "850");
  const outputBox = { x: l.output.x, y: l.output.y + 22, w: l.output.w, h: 104 };
  drawRound(ctx, outputBox, t.surface, s.generated_prompt ? accent : t.border, s.generated_prompt ? 1.5 : 1, 7);
  drawParagraph(ctx, s.generated_prompt, outputBox, t.text, "The generated prompt will appear here...", t, 4);
  const copyFeedback = node._goatedPrompterCopyFeedback;
  const copyLabel = copyFeedback?.until > Date.now() ? copyFeedback.label : "COPY";
  const copyActive = copyLabel === "COPIED!";
  drawRound(ctx, l.copyGenerated, t.surfaceRaised, copyActive ? "#2ED6A3" : s.generated_prompt ? accent : t.border, 1, 5);
  drawText(ctx, copyLabel, l.copyGenerated.x + l.copyGenerated.w / 2, l.copyGenerated.y + l.copyGenerated.h / 2 + 1, 9, copyActive ? "#2ED6A3" : s.generated_prompt ? accent : t.textMuted, "850", "center");
  if (s.generated_prompt) drawText(ctx, "EDIT", outputBox.x + outputBox.w - 26, outputBox.y + outputBox.h - 11, 10, accent, "850", "center");

  drawRound(ctx, l.advanced, t.surface, t.border, 1, 7);
  drawText(ctx, "ADVANCED", l.advanced.x + 14, l.advanced.y + 20, 12, t.textMuted, "850");
  drawText(ctx, node.properties.goatedPrompterAdvancedOpen ? "^" : "v", l.advanced.x + l.advanced.w - 20, l.advanced.y + 20, 14, t.textSecondary, "900", "center");
  if (node.properties.goatedPrompterAdvancedOpen) {
    drawText(ctx, "PRESERVE", l.advanced.x + 14, l.advanced.y + 50, 11, t.textMuted, "850");
    l.preserve.forEach((box) => {
      const on = Boolean(s[box.field]);
      const check = { x: box.x, y: box.y + 3, w: 17, h: 17 };
      drawRound(ctx, check, on ? hexToRgba(accent, 0.25) : t.background, on ? accent : t.border, on ? 2 : 1, 4);
      if (on) drawText(ctx, "✓", check.x + 8.5, check.y + 8.5, 12, accent, "900", "center");
      drawText(ctx, box.label, box.x + 24, box.y + 12, 11, on ? t.text : t.textSecondary, on ? "750" : "600");
    });
    if (l.referenceMapHeader) {
      const manualCount = REFERENCE_MAP_FIELDS.filter(([field]) => s[field] !== "Auto").length;
      const legacyRoles = s.image_1_role !== "Auto" || s.image_2_role !== "Auto";
      const mapStatus = manualCount ? `${manualCount} MANUAL · REST AUTO`
        : legacyRoles ? "LEGACY SHORTCUTS → RESOLVED" : "AUTO RESOLVED BEFORE GENERATION";
      drawText(ctx, "REFERENCE MAP", l.referenceMapHeader.x, l.referenceMapHeader.y + 11, 11, t.textMuted, "850");
      drawText(ctx, mapStatus, l.referenceMapHeader.x + l.referenceMapHeader.w, l.referenceMapHeader.y + 11, 9.5, t.textMuted, "650", "right");
      l.referenceMap.forEach((box) => {
        const source = s[box.field] || "Auto";
        const manual = source !== "Auto";
        drawText(ctx, ellipsize(ctx, box.label, box.segments[0].x - box.x - 9), box.x, box.y + 12, 10, manual ? t.text : t.textSecondary, manual ? "750" : "600");
        box.segments.forEach((segment) => {
          const selected = segment.value === source;
          const fill = selected ? activeFill(palette, 0.88) : segment.disabled ? t.surface : t.background;
          const border = selected ? accent : t.border;
          const foreground = selected ? activeForeground(palette, t.text) : segment.disabled ? t.textMuted : t.textSecondary;
          drawRound(ctx, segment, fill, border, selected ? 1.5 : 1, 5);
          drawText(
            ctx,
            REFERENCE_SOURCE_LABELS[segment.value],
            segment.x + segment.w / 2,
            segment.y + 12,
            9,
            foreground,
            selected ? "850" : segment.disabled ? "550" : "700",
            "center",
          );
          if (segment.disabled) {
            ctx.save();
            ctx.globalAlpha = 0.42;
            ctx.beginPath();
            ctx.moveTo(segment.x + 5, segment.y + segment.h - 5);
            ctx.lineTo(segment.x + segment.w - 5, segment.y + 5);
            ctx.strokeStyle = t.textMuted;
            ctx.lineWidth = 1;
            ctx.stroke();
            ctx.restore();
          }
        });
      });
    }
    drawText(ctx, l.length.label, l.length.x, l.length.y - 7, 11, t.textMuted, "850");
    drawSelector(ctx, { ...l.length, x: l.length.x + 106, y: l.length.y - 22, w: l.length.w - 106, label: "" }, s.prompt_length, t, accent);
    drawText(ctx, "WORKFLOW RULES — OPTIONAL", l.custom.x, l.custom.y - 7, 11, t.textMuted, "850");
    drawRound(ctx, l.custom, t.background, t.border, 1, 6);
    drawText(ctx, WORKFLOW_RULES_HELP, l.custom.x + 10, l.custom.y + 15, 10, t.textMuted, "600");
    const extraStatus = s.custom_instructions.trim() ? "Workflow rules configured — click to edit" : WORKFLOW_RULES_PLACEHOLDER;
    drawText(ctx, ellipsize(ctx, extraStatus, l.custom.w - 20), l.custom.x + 10, l.custom.y + 36, 10.5, s.custom_instructions.trim() ? t.text : t.textMuted, "600");
    drawText(ctx, `DIRECTOR BEHAVIOR — ${s.director_preset}`, l.system.x, l.system.y - 7, 10, t.textMuted, "850");
    drawRound(ctx, l.system, t.background, s.system_prompt_override.trim() ? accent : t.border, s.system_prompt_override.trim() ? 1.5 : 1, 6);
    drawText(ctx, ellipsize(ctx, DIRECTOR_BEHAVIOR_HELP, l.system.w - 18), l.system.x + 10, l.system.y + 15, 10, t.textMuted, "600");
    const systemStatus = node._goatedPrompterPresetsError
      ? "Director unavailable — edit working copy"
      : s.system_prompt_override.trim() ? "Working copy edited — click to inspect" : "Saved behavior — click to inspect";
    drawText(ctx, ellipsize(ctx, systemStatus, l.system.w - 18), l.system.x + 10, l.system.y + 36, 10.5, s.system_prompt_override.trim() ? t.text : t.textMuted, "600");
    drawRound(ctx, l.resetPreset, t.surfaceRaised, t.border, 1, 5);
    drawText(ctx, "RESET", l.resetPreset.x + l.resetPreset.w / 2, l.resetPreset.y + 18, 9, t.textSecondary, "800", "center");
    drawRound(ctx, l.saveAsDirector, t.surfaceRaised, t.border, 1, 5);
    drawText(ctx, node._goatedPrompterSaving ? "WAIT" : "SAVE AS", l.saveAsDirector.x + l.saveAsDirector.w / 2, l.saveAsDirector.y + 18, 8.5, t.textSecondary, "800", "center");
    if (l.deleteDirector) {
      drawRound(ctx, l.deleteDirector, t.surfaceRaised, t.border, 1, 5);
      drawText(ctx, node._goatedPrompterDeleting ? "WAIT" : "DELETE", l.deleteDirector.x + l.deleteDirector.w / 2, l.deleteDirector.y + 18, 8.5, node._goatedPrompterDeleting ? t.textMuted : "#FF5B68", "800", "center");
    }
    const warningMessage = directorWarning(node, s);
    const discoveryMessage = node._goatedPrompterModelsLoading
      ? "Scanning ComfyUI/models/LLM..."
      : node._goatedPrompterModelsError
        ? node._goatedPrompterModelsError
        : warningMessage || directorHint(node, s);
    const discoveryColor = node._goatedPrompterModelsError ? "#FF5B68" : warningMessage ? (t.accentGold || "#FFB800") : t.textSecondary;
    drawText(ctx, ellipsize(ctx, discoveryMessage, l.directorStatus.w), l.directorStatus.x, l.directorStatus.y + 18, 11, discoveryColor, "650");
    drawRound(ctx, l.unloadModel, t.surfaceRaised, accent, 1, 5);
    drawText(ctx, node._goatedPrompterUnloading ? "Unloading..." : "Unload Model", l.unloadModel.x + l.unloadModel.w / 2, l.unloadModel.y + l.unloadModel.h / 2 + 1, 10, node._goatedPrompterUnloading ? t.textMuted : accent, "800", "center");
    drawRound(ctx, l.refreshModels, t.surfaceRaised, t.border, 1, 5);
    drawText(ctx, node._goatedPrompterModelsLoading ? "SCANNING" : "REFRESH", l.refreshModels.x + l.refreshModels.w / 2, l.refreshModels.y + l.refreshModels.h / 2 + 1, 10, t.textSecondary, "800", "center");
    if (s.prompt_model === "Custom") {
      const selectedProfile = directorProfiles(node).find((item) => item.id === s.director_profile);
      const profileLabel = selectedProfile
        ? `${selectedProfile.label}${selectedProfile.vision_ready ? "" : " — Incomplete"}`
        : "Select discovered profile (optional)";
      drawSelector(ctx, l.customProfile, profileLabel, t, accent);
    }
  }

  drawRound(ctx, l.appearance, t.surface, t.border, 1, 7);
  drawPaletteIcon(ctx, l.appearance.x + 14, l.appearance.y + 11, accent, t);
  drawText(ctx, "APPEARANCE", l.appearance.x + 42, l.appearance.y + 20, 12, t.textMuted, "850");
  drawText(ctx, node.properties.goatedPrompterAppearanceOpen ? "^" : "v", l.appearance.x + l.appearance.w - 20, l.appearance.y + 20, 14, t.textSecondary, "900", "center");
  if (node.properties.goatedPrompterAppearanceOpen) {
    drawText(ctx, "THEME", l.appearance.x + 14, l.appearance.y + 56, 11, t.textMuted, "850");
    l.themeButtons.forEach((box) => {
      const on = node.properties.goatedPrompterTheme === box.name;
      drawRound(ctx, box, on ? activeFill(palette, 0.18) : t.surfaceRaised, on ? accent : t.border, on ? 2 : 1, 5);
      drawText(ctx, box.name, box.x + box.w / 2, box.y + box.h / 2, 11, on ? activeForeground(palette, t.text) : t.textSecondary, on ? "800" : "650", "center");
    });
    const contrastOn = node.properties.goatedPrompterContrast;
    drawRound(ctx, l.contrast, contrastOn ? activeFill(palette, 0.18) : t.surfaceRaised, contrastOn ? palette.accentBorder : t.border, contrastOn ? 2 : 1, 5);
    const knobSize = 10;
    const knobX = l.contrast.x + l.contrast.w - 16;
    const knobY = l.contrast.y + l.contrast.h / 2;
    drawText(ctx, "Contrast", l.contrast.x + 8, l.contrast.y + l.contrast.h / 2 + 1, 10, contrastOn ? activeForeground(palette, t.text) : t.textSecondary, "750");
    ctx.beginPath(); ctx.arc(knobX, knobY, knobSize / 2, 0, Math.PI * 2);
    ctx.fillStyle = contrastOn ? activeForeground(palette, t.text) : t.textMuted; ctx.fill();
    drawText(ctx, "ACCENT", l.appearance.x + 14, l.appearance.y + 94, 11, t.textMuted, "850");
    l.swatches.forEach((swatch) => {
      ctx.beginPath(); ctx.arc(swatch.x + 9, swatch.y + 9, 8, 0, Math.PI * 2); ctx.fillStyle = swatch.color; ctx.fill();
      if (normalizeHex(swatch.color) === normalizeHex(accent)) { ctx.lineWidth = 2.5; ctx.strokeStyle = t.text; ctx.stroke(); }
    });
    drawText(ctx, `Hex ${accent}`, l.customAccent.x, l.customAccent.y + 10, 11, t.textSecondary, "700");
    drawText(ctx, "Reset Accent", l.resetAccent.x, l.resetAccent.y + 10, 11, t.textSecondary, "700");
  }

  const status = node._goatedPrompterStatus || { kind: "idle", message: "Ready" };
  const statusColor = status.kind === "success" ? "#2ED6A3" : status.kind === "error" ? "#FF5B68" : status.kind === "generating" ? accent : t.textMuted;
  ctx.beginPath(); ctx.arc(l.footer.x + 5, l.footer.y + 10, 3.5, 0, Math.PI * 2); ctx.fillStyle = statusColor; ctx.fill();
  drawText(ctx, ellipsize(ctx, status.message, l.footer.w - 18), l.footer.x + 14, l.footer.y + 10, 11, statusColor, "600");
}

function editorDialog(node, field) {
  const t = THEME_TOKENS[node.properties?.goatedPrompterTheme] || THEME_TOKENS.Dark;
  const accent = normalizeHex(node.properties?.goatedPrompterAccent) || DEFAULT_ACCENT;
  const palette = buildAccentPalette(accent, Boolean(node.properties?.goatedPrompterContrast));
  const titles = { idea: "What Do You Want?", generated_prompt: "Generated Prompt", custom_instructions: "Workflow Rules — Optional", system_prompt_override: "Director Behavior" };
  const overlay = document.createElement("div");
  overlay.style.cssText = "position:fixed;inset:0;z-index:100000;background:rgba(0,0,0,.62);display:flex;align-items:center;justify-content:center;padding:24px;";
  const panel = document.createElement("div");
  panel.style.cssText = `box-sizing:border-box;width:min(760px,94vw);background:${t.background};color:${t.text};border:1px solid ${t.borderStrong};border-radius:12px;padding:18px;box-shadow:0 20px 70px rgba(0,0,0,.5);font:13px/1.45 system-ui,-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif;`;
  const title = document.createElement("div");
  title.textContent = titles[field] || field;
  title.style.cssText = `font-size:15px;font-weight:850;margin-bottom:10px;color:${t.text};`;
  const area = document.createElement("textarea");
  const selectedPreset = activeDirectorPreset(node);
  const storedValue = String(value(node, field, ""));
  area.value = field === "system_prompt_override" && !storedValue.trim()
    ? String(selectedPreset?.base_system_prompt || "") : storedValue;
  area.placeholder = field === "idea"
    ? "Describe the image or the change you want..."
    : field === "custom_instructions"
      ? WORKFLOW_RULES_PLACEHOLDER
      : field === "system_prompt_override" ? DIRECTOR_BEHAVIOR_PLACEHOLDER : "";
  area.style.cssText = `box-sizing:border-box;width:100%;height:min(46vh,420px);resize:vertical;background:${t.surface};color:${t.text};border:1px solid ${t.border};border-radius:7px;padding:12px;outline:none;font:14px/1.5 system-ui,-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif;`;
  const note = document.createElement("div");
  note.textContent = field === "system_prompt_override"
    ? `Reusable behavior that defines how the selected Director analyzes and writes prompts. Editing the workflow copy of ${selectedPreset?.label || value(node, "director_preset", DEFAULT_DIRECTOR_PRESET)}; use Save As to make it reusable.`
    : field === "custom_instructions"
      ? "Optional rules applied only to this workflow."
      : "Ctrl/Cmd + Enter saves.";
  note.style.cssText = `margin-top:8px;color:${t.textMuted};font-size:11px;`;
  const actions = document.createElement("div");
  actions.style.cssText = "display:flex;justify-content:flex-end;gap:8px;margin-top:14px;";
  const cancel = document.createElement("button"); cancel.textContent = "Cancel";
  const save = document.createElement("button"); save.textContent = field === "system_prompt_override" ? "Apply Working Copy" : "Save";
  for (const button of [cancel, save]) button.style.cssText = `border:1px solid ${t.border};border-radius:6px;padding:8px 16px;background:${t.surfaceRaised};color:${t.text};font-weight:750;cursor:pointer;`;
  save.style.background = accent; save.style.borderColor = accent; save.style.color = palette.accentForeground;
  const close = () => overlay.remove();
  const commit = () => {
    const defaultText = String(selectedPreset?.base_system_prompt || "").trim();
    const nextValue = field === "system_prompt_override" && area.value.trim() === defaultText ? "" : area.value;
    if (setValue(node, field, nextValue, field !== "generated_prompt") && field === "generated_prompt") {
      setStatus(node, "success", "Prompt edited manually");
    }
    close();
  };
  cancel.onclick = close; save.onclick = commit; overlay.onclick = (event) => { if (event.target === overlay) close(); };
  area.onkeydown = (event) => { if (event.key === "Escape") close(); if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) commit(); };
  actions.append(cancel, save); panel.append(title, area, note, actions); overlay.append(panel); document.body.append(overlay); area.focus();
}

function choiceMenu(node, field, options, event, afterSelect = null) {
  const choose = (choice) => {
    const selected = typeof choice === "string" ? choice : choice?.content;
    if (!selected) return;
    if (setValue(node, field, selected)) afterSelect?.(selected);
  };
  const Menu = globalThis.LiteGraph?.ContextMenu;
  if (Menu) {
    new Menu(options, { event, callback: choose });
    return;
  }
  const current = String(value(node, field, options[0]));
  choose(options[(options.indexOf(current) + 1) % options.length]);
}

function customProfileMenu(node, event) {
  const profiles = directorProfiles(node);
  if (!profiles.length) {
    node._goatedPrompterModelsError = "No local GGUF model folders discovered — try Refresh Models";
    node.setDirtyCanvas(true, true);
    return;
  }
  const labels = profiles.map((profile) => `${profile.label}${profile.vision_ready ? "" : " — Incomplete"}`);
  const choose = (label) => {
    const index = labels.indexOf(label);
    if (index < 0) return;
    if (!setValue(node, "director_profile", profiles[index].id)) return;
    setValue(node, "director_model_path", "", false);
    setValue(node, "director_mmproj_path", "", false);
  };
  const Menu = globalThis.LiteGraph?.ContextMenu;
  if (Menu) {
    new Menu(labels, { event, callback: (choice) => choose(typeof choice === "string" ? choice : choice?.content) });
    return;
  }
  const current = profiles.findIndex((profile) => profile.id === String(value(node, "director_profile", "")));
  choose(labels[(current + 1) % labels.length]);
}

async function saveAsDirector(node) {
  if (node._goatedPrompterSaving) return;
  const selectedPreset = activeDirectorPreset(node);
  const workingCopy = String(value(node, "system_prompt_override", "")).trim();
  const instructions = workingCopy || String(selectedPreset?.instructions || selectedPreset?.base_system_prompt || "").trim();
  if (!instructions) {
    setStatus(node, "error", "Director Behavior cannot be empty");
    return;
  }
  const proposedName = prompt("Save Director As", "");
  if (proposedName === null) return;
  const name = proposedName.trim();
  if (!name) {
    setStatus(node, "error", "Director name cannot be empty");
    return;
  }
  node._goatedPrompterSaving = true;
  node.setDirtyCanvas(true, true);
  try {
    const response = await api.fetchApi(PRESETS_ROUTE, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, instructions, recommended_mode: state(node).mode }),
    });
    let data = {};
    try { data = await response.json(); } catch { data = {}; }
    if (!response.ok || !data.ok || !data.director?.label) {
      throw new Error(data.error || `Director save failed (${response.status})`);
    }
    await refreshDirectorPresets(node, true);
    setValue(node, "director_preset", data.director.label);
    setValue(node, "system_prompt_override", "", false);
    setStatus(node, "success", `Saved user Director: ${data.director.label}`);
  } catch (error) {
    setStatus(node, "error", error?.message || "Director save failed");
  } finally {
    node._goatedPrompterSaving = false;
    node.setDirtyCanvas(true, true);
  }
}

async function deleteSelectedDirector(node) {
  if (node._goatedPrompterDeleting) return;
  const selectedPreset = activeDirectorPreset(node);
  if (selectedPreset?.source !== "user" || selectedPreset?.protected !== false) {
    setStatus(node, "error", "Built-in Goated Prompter Directors cannot be deleted");
    return;
  }
  if (!globalThis.confirm(`Delete user Director "${selectedPreset.label}"? This cannot be undone.`)) return;
  node._goatedPrompterDeleting = true;
  node.setDirtyCanvas(true, true);
  try {
    const response = await api.fetchApi(PRESETS_ROUTE, {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: selectedPreset.label }),
    });
    let data = {};
    try { data = await response.json(); } catch { data = {}; }
    if (!response.ok || !data.ok) {
      throw new Error(data.error || `Director deletion failed (${response.status})`);
    }
    await refreshDirectorPresets(node, true);
    const recommended = legacyPresetForMode(value(node, "mode", "Enhance"));
    const fallback = directorPresetOptions(node).includes(recommended) ? recommended : DEFAULT_DIRECTOR_PRESET;
    setValue(node, "director_preset", fallback);
    setValue(node, "system_prompt_override", "", false);
    setStatus(node, "success", `Deleted ${selectedPreset.label} · selected ${fallback}`);
  } catch (error) {
    setStatus(node, "error", error?.message || "Director deletion failed");
  } finally {
    node._goatedPrompterDeleting = false;
    node.setDirtyCanvas(true, true);
  }
}

async function unloadModel(node) {
  if (node._goatedPrompterUnloading) return;
  node._goatedPrompterUnloading = true;
  node.setDirtyCanvas(true, true);
  try {
    const response = await api.fetchApi(UNLOAD_ROUTE, { method: "POST" });
    let data = {};
    try { data = await response.json(); } catch { data = {}; }
    if (!response.ok || !data.ok) throw new Error(data.error || `Model unload failed (${response.status})`);
    const message = data.status === "pending"
      ? "Unload queued — active generation will finish first"
      : data.status === "idle"
        ? "No Goated Prompter model is loaded"
        : "Model unloaded — selection preserved";
    setStatus(node, data.status === "pending" ? "idle" : "success", message);
  } catch (error) {
    setStatus(node, "error", error?.message || "Model unload failed");
  } finally {
    node._goatedPrompterUnloading = false;
    node.setDirtyCanvas(true, true);
  }
}

async function generate(node) {
  if (node._goatedPrompterInFlight) return;
  const payload = state(node);
  const imageLinked = connectedReferences(node).length > 0;
  if (!payload.idea.trim()) {
    setStatus(node, "error", "Enter a text prompt first.");
    return;
  }
  const revision = node._goatedPrompterRevision;
  // Also catch widget writes made outside our controls (for example converted inputs).
  const snapshot = JSON.stringify(WIDGET_NAMES.map((name) => value(node, name)));
  const isCurrent = () => node._goatedPrompterRevision === revision
    && JSON.stringify(WIDGET_NAMES.map((name) => value(node, name))) === snapshot;
  node._goatedPrompterInFlight = true;
  setStatus(node, "generating", imageLinked ? "Generating text-only preview..." : "Generating prompt...");
  const generatingStatus = node._goatedPrompterStatus;
  try {
    const response = await api.fetchApi(TEXT_ROUTE, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(textOnlyPayload(payload)) });
    let data = {};
    try { data = await response.json(); } catch { data = {}; }
    if (!isCurrent()) return;
    if (!response.ok || !data.ok || !String(data.prompt || "").trim()) throw new Error(data.error || `Goated Prompter request failed (${response.status})`);
    setValue(node, "generated_prompt", String(data.prompt).trim(), false);
    const generatedWith = data.prompt_model || data.director_profile || data.backend || "configured backend";
    const activePreset = data.director_preset || payload.director_preset;
    setStatus(node, "success", imageLinked ? "Text-only preview — queue graph to ground connected IMAGE" : `Generated with ${generatedWith} · ${activePreset}`);
  } catch (error) {
    if (isCurrent()) setStatus(node, "error", error?.message || "Goated Prompter generation failed");
  } finally {
    node._goatedPrompterInFlight = false;
    if (node._goatedPrompterStatus === generatingStatus) setStatus(node, "idle", "Preview discarded after changes");
    node.setDirtyCanvas(true, true);
  }
}

function handleClick(node, event, pos) {
  const hit = (node._goatedPrompterHits || makeLayout(node).hits).find((box) => pos[0] >= box.x && pos[0] <= box.x + box.w && pos[1] >= box.y && pos[1] <= box.y + box.h);
  if (!hit) return false;
  if (hit.kind === "advanced") {
    node.properties.goatedPrompterAdvancedOpen = !node.properties.goatedPrompterAdvancedOpen;
  } else if (hit.kind === "appearance") {
    node.properties.goatedPrompterAppearanceOpen = !node.properties.goatedPrompterAppearanceOpen;
  } else if (hit.kind === "theme") {
    node.properties.goatedPrompterTheme = hit.field;
  } else if (hit.kind === "contrast") {
    node.properties.goatedPrompterContrast = !node.properties.goatedPrompterContrast;
  } else if (hit.kind === "accent") {
    node.properties.goatedPrompterAccent = normalizeHex(hit.field) || DEFAULT_ACCENT;
  } else if (hit.kind === "customAccent") {
    const selected = normalizeHex(prompt("Accent hex color", node.properties.goatedPrompterAccent || DEFAULT_ACCENT));
    if (selected) node.properties.goatedPrompterAccent = selected;
  } else if (hit.kind === "resetAccent") {
    node.properties.goatedPrompterAccent = DEFAULT_ACCENT;
  } else if (hit.kind === "copyGenerated") {
    copyGeneratedPrompt(node);
  } else if (hit.kind === "text") {
    editorDialog(node, hit.field);
  } else if (hit.kind === "resetPreset") {
    setValue(node, "system_prompt_override", "");
    setStatus(node, "idle", `Reset to saved ${value(node, "director_preset", DEFAULT_DIRECTOR_PRESET)} behavior`);
  } else if (hit.kind === "saveAsDirector") {
    saveAsDirector(node);
  } else if (hit.kind === "deleteDirector") {
    deleteSelectedDirector(node);
  } else if (hit.kind === "toggle") {
    setValue(node, hit.field, !Boolean(value(node, hit.field, false)));
  } else if (hit.kind === "referenceSource") {
    if (hit.disabled) return true;
    setValue(node, hit.field, hit.value);
    setValue(node, "image_1_role", "Auto", false);
    setValue(node, "image_2_role", "Auto", false);
  } else if (hit.kind === "choice") {
    const options = hit.field === "mode" ? MODES
      : hit.field === "target_model" ? TARGETS
        : hit.field === "creativity" ? CREATIVITY
          : hit.field === "prompt_model" ? promptModelOptions(node)
            : hit.field === "director_preset" ? directorPresetOptions(node)
              : LENGTHS;
    choiceMenu(node, hit.field, options, event, () => {
      if (hit.field === "director_preset") {
        setValue(node, "system_prompt_override", "", false);
      }
    });
    if (hit.field === "prompt_model" && !node._goatedPrompterDiscovery) refreshDirectorProfiles(node, false);
  } else if (hit.kind === "directorProfile") {
    customProfileMenu(node, event);
  } else if (hit.kind === "refreshModels") {
    refreshDirectorProfiles(node, true);
  } else if (hit.kind === "unloadModel") {
    unloadModel(node);
  } else if (hit.kind === "generate") {
    generate(node);
  } else return false;
  node.setDirtyCanvas(true, true);
  return true;
}

app.registerExtension({
  name: "GoatedPrompter",
  beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData.name !== NODE_NAME) return;
    const created = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      const result = created?.apply(this, arguments);
      ensureProperties(this); detachWidgets(this); configureReferenceInputs(this); this.size = this.size || [460, 450]; this.resizable = true; this.serialize_widgets = true;
      refreshDirectorProfiles(this, false);
      refreshDirectorPresets(this, false);
      return result;
    };
    const configured = nodeType.prototype.onConfigure;
    nodeType.prototype.onConfigure = function (info) {
      this._goatedPrompterRevision = {};
      const result = configured?.apply(this, arguments);
      ensureProperties(this); detachWidgets(this, info?.widgets_values); configureReferenceInputs(this); this._goatedPrompterStatus = { kind: "idle", message: value(this, "generated_prompt", "") ? "Loaded generated prompt" : "Ready" };
      refreshDirectorProfiles(this, false);
      refreshDirectorPresets(this, false);
      return result;
    };
    const executed = nodeType.prototype.onExecuted;
    nodeType.prototype.onExecuted = function (message) {
      const result = executed?.apply(this, arguments);
      const queuePrompt = promptFromExecution(message);
      if (queuePrompt !== null) {
        this._goatedPrompterRevision = {};
        setValue(this, "generated_prompt", queuePrompt, false);
        setStatus(this, "success", "Generated Prompt updated from workflow result");
      }
      return result;
    };
    const serialize = nodeType.prototype.serialize;
    nodeType.prototype.serialize = function () {
      const data = serialize?.apply(this, arguments) || {};
      data.widgets_values = WIDGET_NAMES.map((name) => value(this, name));
      data.properties = { ...(data.properties || {}), ...(this.properties || {}) };
      return data;
    };
    nodeType.prototype.onDrawForeground = function (ctx) { drawUI(this, ctx); };
    const connectionsChanged = nodeType.prototype.onConnectionsChange;
    nodeType.prototype.onConnectionsChange = function () {
      this._goatedPrompterRevision = {};
      const result = connectionsChanged?.apply(this, arguments);
      configureReferenceInputs(this);
      return result;
    };
    const mouseDown = nodeType.prototype.onMouseDown;
    nodeType.prototype.onMouseDown = function (event, pos) { if (handleClick(this, event, pos)) return true; return mouseDown?.apply(this, arguments); };
    const resize = nodeType.prototype.onResize;
    nodeType.prototype.onResize = function () { const result = resize?.apply(this, arguments); this.setDirtyCanvas(true, true); return result; };
  },
});
