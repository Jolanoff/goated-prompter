import test from "node:test";
import assert from "node:assert/strict";
import { readTheme, saveTheme, THEME_KEY } from "./theme.js";

test("theme defaults to dark and ignores unknown saved preferences", () => {
  assert.equal(readTheme(), "dark");
  for (const value of [null, "", "system", "invalid", "dark"]) {
    assert.equal(readTheme({ getItem: () => value }), "dark");
  }
});

test("explicit light and dark preferences persist independently of workspace data", () => {
  const values = new Map();
  const storage = { getItem: (key) => values.get(key), setItem: (key, value) => values.set(key, value) };
  saveTheme(storage, "light");
  assert.equal(values.get(THEME_KEY), "light");
  assert.equal(readTheme(storage), "light");
  saveTheme(storage, "dark");
  assert.equal(readTheme(storage), "dark");
  assert.equal(values.size, 1);
});

test("blocked storage does not prevent rendering or switching themes", () => {
  const storage = { getItem() { throw new Error("Blocked"); }, setItem() { throw new Error("Blocked"); } };
  assert.equal(readTheme(storage), "dark");
  assert.doesNotThrow(() => saveTheme(storage, "light"));
});
