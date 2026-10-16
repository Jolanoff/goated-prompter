import { test } from "node:test";
import assert from "node:assert/strict";
import { datasetRequestSignature, nextDatasetSeed } from "./datasetState.js";

test("the next batch seed is kept, increased by one or redrawn", () => {
  assert.equal(nextDatasetSeed({ seed: 41, seed_mode: "fixed" }), 41);
  assert.equal(nextDatasetSeed({ seed: 41, seed_mode: "increment" }), 42);
  assert.equal(nextDatasetSeed({ seed: 4294967295, seed_mode: "increment" }), 0);
  assert.equal(nextDatasetSeed({ seed: 41, seed_mode: "randomize" }, () => 0.5), 2147483648);
});

test("the request signature ignores key order but detects every setting change", () => {
  const input = { subject: "Two people boxing", trigger: "person 1, person 2", amount: 2, target: "Generic",
    length: "Medium", constraints: "Arena. Gloves." };
  const signature = datasetRequestSignature(input);
  assert.equal(signature, datasetRequestSignature(Object.fromEntries(Object.entries(input).reverse())));
  for (const patch of [{ subject: "New concept" }, { trigger: "new_token" }, { amount: 3 }, { target: "Anima" },
    { constraints: "Blond hair" }, { length: "Detailed" }]) {
    assert.notEqual(signature, datasetRequestSignature({ ...input, ...patch }));
  }
});
