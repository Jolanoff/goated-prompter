import { test } from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { transformWithEsbuild } from "vite";

test("vocabulary preparation is an explicit separate action and does not convert on render", async () => {
  const url = new URL("./VocabularyPreparation.jsx", import.meta.url);
  const { code } = await transformWithEsbuild(await readFile(url, "utf8"), url.pathname,
    { loader: "jsx", jsx: "automatic", sourcemap: false });
  const linked = code.replace(/from (["'])([^"']+)\1/g, (_match, _quote, specifier) =>
    `from ${JSON.stringify(specifier.startsWith(".") ? new URL(specifier, url).href : import.meta.resolve(specifier))}`);
  const Component = (await import(`data:text/javascript;base64,${Buffer.from(linked).toString("base64")}`)).default;
  let conversions = 0;
  const markup = renderToStaticMarkup(createElement(Component,
    { busy: false, noEngine: true, onGenerate: () => { conversions += 1; } }));
  assert.equal(conversions, 0);
  assert.match(markup, /generation never runs conversion automatically/);
  assert.match(markup, /Open prepared records for review/);
  assert.doesNotMatch(markup, /Approve selected records/);
});
