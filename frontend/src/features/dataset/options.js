// Dataset types and identity-policy labels.
// Keep triggerTypes in sync with goated_prompter/options/dataset.py (checked by tests/unit/shared/test_option_parity.py).

export const triggerTypes = ["Character", "Multiple characters", "Animal", "Object / product", "Visual style",
  "Location / environment", "Brand / logo", "Typography / text", "Concept", "Custom"];

export const identityLabels = {
  fixed: "Fixed; preserve the specified identities",
  random_per_prompt: "Randomized per independent prompt; consistent within its idea and scene",
  not_applicable: "No character identity applies",
  mixed: "Mixed identity policies; follow the requirements for each subject and guided input",
};
