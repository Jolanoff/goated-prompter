import { maxSeed } from "./options.js";

/** The seed for the next batch run, like ComfyUI's control: same, last plus one, or new. */
export function nextDatasetSeed(draft, random = Math.random) {
  const seed = Number.isInteger(draft.seed) ? draft.seed : 0;
  if (draft.seed_mode === "fixed") return seed;
  if (draft.seed_mode === "increment") return seed >= maxSeed ? 0 : seed + 1;
  return Math.floor(random() * (maxSeed + 1));
}

export function datasetConfirmationPayload(review) {
  return { brief: review.brief, input: review.input, operation: review.operation,
    confirmation_token: review.confirmation_token };
}
