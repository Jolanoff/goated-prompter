// Presentation only: the order built-in Directors are listed in. Their names come from the backend.
const builtinOrder = new Map([
  "general_director",
  "prompt_enhancer",
  "maximum_detail_director",
  "reverse_engineer",
  "face_identity_analyst",
  "subject_appearance_analyst",
  "reference_composer",
  "surgical_edit",
  "krea_2_identity_edit",
  "style_transfer_director",
  "krea_2_high_detail",
  "krea_2_pose_lock",
  "arms_length_selfie",
  "mirror_selfie",
  "first_person_pov",
  "fashion_editorial",
  "boudoir_intimate",
  "character_director",
  "archviz_director",
  "product_director",
  "dataset_caption_director",
  "video_director",
  "minimax_director",
  "nsfw_director",
].map((id, index) => [id, index]));

export function presetDisplayLabel(preset) {
  return preset.label;
}

export function orderDisplayPresets(presets) {
  const rank = (preset) =>
    preset.source === "builtin"
      ? builtinOrder.get(preset.id) ?? builtinOrder.size
      : builtinOrder.size + 1;
  return [...presets].sort((a, b) => rank(a) - rank(b));
}
