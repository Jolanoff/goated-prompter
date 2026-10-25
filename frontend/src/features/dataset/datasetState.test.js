import { test } from "node:test";
import assert from "node:assert/strict";
import { nextDatasetSeed } from "./datasetState.js";

test("the next batch seed is kept, increased by one or redrawn", () => {
  assert.equal(nextDatasetSeed({ seed: 41, seed_mode: "fixed" }), 41);
  assert.equal(nextDatasetSeed({ seed: 41, seed_mode: "increment" }), 42);
  assert.equal(nextDatasetSeed({ seed: 4294967295, seed_mode: "increment" }), 0);
  assert.equal(nextDatasetSeed({ seed: 41, seed_mode: "randomize" }, () => 0.5), 2147483648);
});
