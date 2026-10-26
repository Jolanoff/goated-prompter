// Dataset types, consistency, seed modes, Directors Dataset does not offer and identity-policy labels.
// Keep triggerTypes, consistencyParts, consistencyLevels, typeConsistency, seedModes, maxSeed, excludedDirectors,
// triggerKinds, triggerExpansions and maxTriggers in sync with goated_prompter/options/dataset.py
// (checked by tests/unit/shared/test_option_parity.py).

export const triggerTypes = ["Character", "Multiple characters", "Animal", "Act variety", "Pose / action",
  "Outfit / clothing", "Expression", "Object / product", "Brand / logo", "Typography / text", "Location / environment",
  "Lighting", "Camera / composition", "Visual style", "Concept", "Custom"];

// The parts of an image a dataset can hold the same, and how much each one stays the same.
export const consistencyParts = [["subject", "Subject"], ["clothing", "Clothing"], ["action", "Action / pose"],
  ["expression", "Expression"], ["place", "Place"], ["objects", "Objects"], ["camera", "Camera"], ["light", "Light"],
  ["mood", "Mood / effects"]];

export const consistencyLevels = [["locked", "Locked"], ["themed", "Themed"], ["free", "Free"]];

// Each dataset type's default levels; a part not listed is free.
export const typeConsistency = {
  "Character": { "subject": "themed" },
  "Multiple characters": { "subject": "themed" },
  "Animal": { "subject": "themed" },
  "Act variety": { "action": "themed" },
  "Pose / action": { "action": "locked" },
  "Outfit / clothing": { "clothing": "locked" },
  "Expression": { "expression": "locked" },
  "Object / product": { "objects": "locked" },
  "Brand / logo": { "objects": "locked" },
  "Typography / text": { "objects": "locked" },
  "Location / environment": { "place": "themed" },
  "Lighting": { "light": "locked" },
  "Camera / composition": { "camera": "locked" },
  "Visual style": {},
  "Concept": {},
  "Custom": {}
};

export const seedModes = [["randomize", "Randomize"], ["fixed", "Fixed"], ["increment", "Increment"]];

// What a trigger stands for, and how it is used: exact text placed by the app, its meaning written by the model, or both.
export const triggerKinds = [["character", "Character"], ["style", "Style"], ["outfit", "Outfit"], ["object", "Object / concept"],
  ["other", "Other"]];

export const triggerExpansions = [["off", "Exact text"], ["on", "Meaning only"], ["both", "Exact text + meaning"]];

export const maxTriggers = 20;

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
