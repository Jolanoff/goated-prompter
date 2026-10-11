// Prompt details that Refine and other workflows can lock.
// Keep in sync with goated_prompter/options/detail_locks.py (checked by tests/unit/shared/test_option_parity.py).

// Visual style choices for Builder and Dataset.
// Keep in sync with goated_prompter/options/styles.py (checked by tests/unit/shared/test_option_parity.py).
export const styles = ["Auto", "Anime", "Realistic", "Illustration", "3D render", "Product", "Painting"];

export const lockOptions = [
  ["identity", "Identity / subject"], ["outfit", "Outfit"], ["pose", "Pose"],
  ["scene", "Setting"], ["composition", "Composition"], ["camera", "Camera"],
  ["lighting", "Lighting"], ["colors", "Colors"], ["materials", "Materials"], ["style", "Style"],
];
