// Dataset types, seed modes, Directors Dataset does not offer and identity-policy labels.
// Keep triggerTypes, seedModes, maxSeed and excludedDirectors in sync with goated_prompter/options/dataset.py
// (checked by tests/unit/shared/test_option_parity.py).

export const triggerTypes = ["Character", "Multiple characters", "Animal", "Object / product", "Visual style",
  "Location / environment", "Brand / logo", "Typography / text", "Concept", "Custom"];

export const seedModes = [["randomize", "Randomize"], ["fixed", "Fixed"], ["increment", "Increment"]];

export const maxSeed = 4294967295;

// Directors that need reference images, edit a source image or write video; Dataset writes text-to-image prompts.
export const excludedDirectors = ["reverse_engineer", "surgical_edit", "image_edit_director", "face_identity_analyst",
  "subject_appearance_analyst", "reference_composer", "krea_2_pose_lock", "krea_2_identity_edit", "style_transfer_director",
  "video_director", "minimax_director", "minimax_h3_director"];

export const identityLabels = {
  fixed: "Fixed; preserve the specified identities",
  random_per_prompt: "Randomized per independent prompt; consistent within its idea and scene",
  not_applicable: "No character identity applies",
  mixed: "Mixed identity policies; follow the requirements for each subject and guided input",
};
