import test from "node:test";
import assert from "node:assert/strict";
import { promptDiff } from "./workflows/promptDiff.js";

function verify(before, after) {
  const parts = promptDiff(before, after);
  assert.equal(parts.filter((part) => part.kind !== "added").map((part) => part.text).join(""), before);
  assert.equal(parts.filter((part) => part.kind !== "removed").map((part) => part.text).join(""), after);
  return parts;
}

test("diff retains exact text, whitespace and multiple separate edits", () => {
  const parts = verify("A red coat, soft light.\nWide shot.", "A blue coat, hard light.\nWide shot.");
  assert.equal(parts.filter((part) => part.kind === "added").map((part) => part.text).join(""), "bluehard");
  verify("", "New prompt");
  verify("Old prompt", "");
  assert.deepEqual(verify("Same prompt", "Same prompt"), [{ kind: "same", text: "Same prompt" }]);
});

test("large diff falls back without quadratic allocation or losing text", () => {
  const parts = verify("old ".repeat(20000), "new ".repeat(20000));
  assert.ok(parts.length <= 3);
});

test("varied inputs always reconstruct both documents exactly", () => {
  const samples = ["", "red", "blue", "red blue", "blue red", " a \n b", "a  b", "猫 🐐 light"];
  for (const before of samples) for (const after of samples) verify(before, after);
});
