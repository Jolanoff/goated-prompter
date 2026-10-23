// Prompt details that Refine and other workflows can lock.
// Keep in sync with goated_prompter/options/detail_locks.py (checked by tests/unit/shared/test_option_parity.py).

// Visual style choices for Builder and Dataset: families, then "Family / Sub-style" values.
// Keep in sync with goated_prompter/options/styles.py STYLE_NAMES (checked by tests/unit/shared/test_option_parity.py).
export const styles = [
  "Auto", "Anime", "Realistic", "Cinematic", "Semi-realistic", "Illustration",
  "Concept art", "Comic", "Manga", "Pixel art", "Sketch", "3D render",
  "Product", "Painting", "Anime / Modern TV anime", "Anime / 90s cel anime", "Anime / Anime film", "Anime / Watercolor anime",
  "Anime / Chibi", "Cinematic / Blockbuster", "Cinematic / Indie drama", "Cinematic / Neo-noir", "Cinematic / Vintage film", "Semi-realistic / Painterly",
  "Semi-realistic / Game splash art", "Semi-realistic / Soft fantasy", "Illustration / Children's book", "Illustration / Flat vector", "Illustration / Ink and wash", "Illustration / Fashion illustration",
  "Illustration / Retro poster", "Concept art / Environment", "Concept art / Character", "Concept art / Keyframe", "Comic / Superhero", "Comic / Noir",
  "Comic / Ligne claire", "Comic / Webtoon", "Manga / Shonen", "Manga / Shojo", "Manga / Seinen", "Pixel art / 8-bit",
  "Pixel art / 16-bit", "Pixel art / Isometric", "Sketch / Pencil", "Sketch / Charcoal", "Sketch / Ink pen", "3D render / Stylized cartoon",
  "3D render / Realistic CGI", "3D render / Low poly", "3D render / Clay", "Product / Studio white", "Product / Lifestyle", "Product / Dark and moody",
  "Painting / Oil", "Painting / Watercolor", "Painting / Gouache", "Painting / Impressionist", "Painting / Ink wash",
];
const subStyleSeparator = " / ";
// How a Realistic image was photographed. Keep in sync with CAPTURE_NAMES.
export const captures = ["Auto", "Pro camera", "Phone snapshot", "Analog film", "Instant film", "Disposable camera", "Black-and-white film", "Medium format", "Studio portrait",
  "Fashion editorial", "Documentary", "Street photography", "Flash snapshot", "Mirror selfie", "Webcam", "Security camera", "Action camera", "Drone"];
// The shape every image of a dataset is made in. Keep in sync with ASPECT_RATIO_NAMES.
export const aspectRatios = ["Auto", "1:1", "4:5", "3:4", "2:3", "9:16", "5:4", "4:3", "3:2", "16:9"];
// Styles a target cannot render (Anima draws anime, never photographs). Keep in sync with UNSUPPORTED_STYLES.
export const unsupportedStyles = { Anima: ["Realistic", "Cinematic"] };

/** The family of a style value ("Anime" for "Anime / Chibi"). */
export function styleFamily(value) {
  return (value || "Auto").split(subStyleSeparator)[0];
}

/** The style families offered for a target, as select choices; the current family stays listed so the select never
 * blanks. */
export function styleChoices(all, target, current) {
  const family = styleFamily(current);
  return all.filter((value) => !value.includes(subStyleSeparator))
    .filter((value) => value === family || !(unsupportedStyles[target] || []).includes(value))
    .map((value) => ({ value, label: value }));
}

/** The sub-styles of the current family as select choices ("Any" keeps the family alone); [] when it has none. */
export function subStyleChoices(all, current) {
  const family = styleFamily(current);
  const subs = all.filter((value) => value.startsWith(family + subStyleSeparator));
  return subs.length ? [{ value: family, label: "Any" },
    ...subs.map((value) => ({ value, label: value.slice(family.length + subStyleSeparator.length) }))] : [];
}

export const lockOptions = [
  ["identity", "Identity / subject"], ["outfit", "Outfit"], ["pose", "Pose"],
  ["scene", "Setting"], ["composition", "Composition"], ["camera", "Camera"],
  ["lighting", "Lighting"], ["colors", "Colors"], ["materials", "Materials"], ["style", "Style"],
];
