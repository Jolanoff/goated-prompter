const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const test = require("node:test");

const context = vm.createContext({});
const source = fs.readFileSync(path.join(__dirname, "../comfyui_web/shared/ui_shared.js"), "utf8");
vm.runInContext(source.replace(/^export /gm, ""), context);

test("ellipsis respects exact, short, and empty width budgets", () => {
  const ctx = { measureText: (text) => ({ width: Array.from(text).length }) };
  for (const [text, width, expected] of [
    ["", 0, ""], ["abc", 3, "abc"], ["abcdefghij", 8, "abcde..."],
    ["abcdefghij", 5, "ab..."], ["abcdefghij", 3, "..."], ["abcdefghij", 2, ""],
    ["\u{1F600}".repeat(10), 5, "\u{1F600}\u{1F600}..."],
  ]) {
    assert.equal(context.ellipsize(ctx, text, width), expected);
  }
});

test("long labels use logarithmically many canvas measurements", () => {
  let measurements = 0;
  const ctx = { measureText(text) { measurements++; return { width: text.length }; } };
  assert.equal(context.ellipsize(ctx, "x".repeat(10000), 20), "x".repeat(17) + "...");
  assert.ok(measurements <= 16, `${measurements} measurements`);
});
