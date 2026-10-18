// Prompt details that Refine and other workflows can lock.
// Keep in sync with goated_prompter/options/detail_locks.py (checked by tests/unit/shared/test_option_parity.py).

// Visual style choices for Builder and Dataset.
// Keep in sync with goated_prompter/options/styles.py (checked by tests/unit/shared/test_option_parity.py).
export const styles = ["Auto", "Anime", "Realistic", "Illustration", "3D render", "Product", "Painting"];
// How a Realistic image was photographed. Keep in sync with CAPTURE_NAMES.
export const captures = ["Auto", "Pro camera", "Phone snapshot", "Analog film"];
// Styles a target cannot render (Anima draws anime, never photographs). Keep in sync with UNSUPPORTED_STYLES.
export const unsupportedStyles = { Anima: ["Realistic"] };

/** The styles offered for a target, as select choices; the current value stays listed so the select never blanks. */
export function styleChoices(all, target, current) {
  return all.filter((value) => value === current || !(unsupportedStyles[target] || []).includes(value))
    .map((value) => ({ value, label: value }));
}

export const lockOptions = [
  ["identity", "Identity / subject"], ["outfit", "Outfit"], ["pose", "Pose"],
  ["scene", "Setting"], ["composition", "Composition"], ["camera", "Camera"],
  ["lighting", "Lighting"], ["colors", "Colors"], ["materials", "Materials"], ["style", "Style"],
];
