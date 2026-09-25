import test from "node:test";
import assert from "node:assert/strict";
import { insertReference, nextReference, parseReferences } from "./workflows/minimaxReferences.js";

test("symbolic references normalize case, deduplicate and flag out-of-range numbers", () => {
  assert.deepEqual(parseReferences("<IMAGE1> <video3> <image1> <audio4> <image10> <image01>"),
    { references: ["image1", "video3"], invalid: ["<audio4>", "<image10>", "<image01>"] });
});
test("insertion respects cursor/selection, appending and punctuation", () => {
  assert.deepEqual(insertReference("Use here.", "image1", 4, 8), { text: "Use <image1>.", cursor: 12 });
  assert.equal(insertReference("A dancer", "video1").text, "A dancer <video1>");
  assert.equal(insertReference("moveshere", "video1", 5).text, "moves <video1> here");
});
test("allocations preserve sparse identifiers and respect modality and combined limits", () => {
  const refs = ["image9", "image1", "video1"];
  assert.equal(nextReference("image", refs), "image2");
  assert.deepEqual(refs, ["image9", "image1", "video1"]);
  assert.equal(nextReference("video", ["video1", "video2", "video3"]), null);
  assert.equal(nextReference("audio", [...Array.from({ length: 9 }, (_, i) => `image${i + 1}`), "video1", "video2", "video3"]), null);
});
