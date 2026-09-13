// Presentation only: never replace canonical preset names or instructions.
const builtinTitles = new Map([
  ["general_director", "General-Purpose Prompt"],
  ["prompt_enhancer", "Polish a Rough Prompt"],
  ["maximum_detail_director", "Detailed Scene Description"],
  ["reverse_engineer", "Recreate a Reference Image"],
  ["face_identity_analyst", "Describe Facial Features"],
  ["subject_appearance_analyst", "Describe Face & Body"],
  ["reference_composer", "Combine Reference Images"],
  ["surgical_edit", "Edit Only the Requested Details"],
  ["krea_2_identity_edit", "Krea 2 Identity Edit"],
  ["style_transfer_director", "Change the Visual Style"],
  ["krea_2_high_detail", "Krea 2 Detailed Prompt"],
  ["krea_2_pose_lock", "Krea 2 Match Reference Pose"],
  ["photography_director", "Photography Director"],
  ["smartphone_realism", "Casual Phone Photo"],
  ["arms_length_selfie", "Front-Camera Selfie"],
  ["mirror_selfie", "Mirror Selfie"],
  ["first_person_pov", "First-Person View"],
  ["fashion_editorial", "Fashion Photography"],
  ["vintage_analog", "Vintage Film Photography"],
  ["boudoir_intimate", "Boudoir Photography"],
  ["krea_2_smartphone_realism", "Krea 2 Phone Photo"],
  ["character_director", "Character Director"],
  ["archviz_director", "Architecture & Interiors"],
  ["product_director", "Product Photography"],
  ["dataset_caption_director", "Dataset & LoRA Caption"],
  ["video_director", "Video Action & Camera Movement"],
  ["minimax_h3_director", "MiniMax H3 Video Shot"],
]);
const builtinOrder = new Map(
  [...builtinTitles.keys()].map((id, index) => [id, index]),
);

export function presetDisplayLabel(preset) {
  return preset.source === "builtin"
    ? builtinTitles.get(preset.id) ?? preset.label
    : preset.label;
}

export function orderDisplayPresets(presets) {
  const rank = (preset) =>
    preset.source === "builtin"
      ? builtinOrder.get(preset.id) ?? builtinOrder.size
      : builtinOrder.size + 1;
  return [...presets].sort((a, b) => rank(a) - rank(b));
}
