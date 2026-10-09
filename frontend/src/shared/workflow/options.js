// Prompt details that Refine and other workflows can lock.
// Keep in sync with goated_prompter/options/detail_locks.py (checked by tests/unit/shared/test_option_parity.py).

export const lockOptions = [
  ["identity", "Identity / subject"], ["outfit", "Outfit"], ["pose", "Pose"],
  ["scene", "Setting"], ["composition", "Composition"], ["camera", "Camera"],
  ["lighting", "Lighting"], ["colors", "Colors"], ["materials", "Materials"], ["style", "Style"],
];
