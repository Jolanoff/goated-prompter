import { maxSeed } from "./options.js";

function canonicalValue(value) {
  if (Array.isArray(value)) return value.map(canonicalValue);
  if (value && typeof value === "object") return Object.fromEntries(
    Object.keys(value).sort().map((key) => [key, canonicalValue(value[key])]),
  );
  return value;
}

/** The reviewed request; a different signature at Confirm means the settings changed during review. */
export function datasetRequestSignature(draft) {
  return JSON.stringify(canonicalValue(draft || {}));
}

export function datasetReviewQuestions(brief) {
  return brief?.clarifications || [];
}

export function canConfirmDatasetReview(review, busy, additions = "") {
  return review?.status === "ready" && !!review.brief && !!review.confirmation_token && !busy &&
    !additions.trim() && !datasetReviewQuestions(review.brief).length;
}

/** The seed for the next batch run, like ComfyUI's control: same, last plus one, or new. */
export function nextDatasetSeed(draft, random = Math.random) {
  const seed = Number.isInteger(draft.seed) ? draft.seed : 0;
  if (draft.seed_mode === "fixed") return seed;
  if (draft.seed_mode === "increment") return seed >= maxSeed ? 0 : seed + 1;
  return Math.floor(random() * (maxSeed + 1));
}

export function datasetConfirmationPayload(review) {
  return { brief: review.brief, input: review.input, operation: review.operation,
    confirmation_token: review.confirmation_token, vocabulary_packs: [...(review.vocabulary_packs || [])],
    ...(review.visual_direction ? { visual_direction: structuredClone(review.visual_direction) } : {}) };
}
