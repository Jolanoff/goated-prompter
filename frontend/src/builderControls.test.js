import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { transformWithEsbuild } from "vite";

async function jsxModuleUrl(sourceUrl) {
  const { code } = await transformWithEsbuild(await readFile(sourceUrl, "utf8"), sourceUrl.pathname,
    { loader: "jsx", jsx: "automatic", sourcemap: false });
  const imports = [...code.matchAll(/from (["'])([^"']+)\1/g)];
  const replacements = await Promise.all(imports.map(async ([statement, , specifier]) => {
    const url = specifier.startsWith(".") ? new URL(specifier, sourceUrl) : new URL(import.meta.resolve(specifier));
    return [statement, `from ${JSON.stringify(url.pathname.endsWith(".jsx") ? await jsxModuleUrl(url) : url.href)}`];
  }));
  let linked = code;
  for (const [statement, replacement] of replacements) linked = linked.replaceAll(statement, replacement);
  return `data:text/javascript;base64,${Buffer.from(linked).toString("base64")}`;
}

test("Builder has no Planning control or planning notice, including recovered planned jobs", async () => {
  const Builder = (await import(await jsxModuleUrl(new URL("./workflows/BuilderTab.jsx", import.meta.url)))).default;
  const markup = renderToStaticMarkup(createElement(Builder, {
    settings: { idea: "A portrait", custom_instructions: "", planning_mode: "Always", generated_prompt: "" },
    inputs: { mode: [["Enhance"], {}], director_preset: [["general_director"], {}],
      target_model: [["Generic"], {}], creativity: [["Balanced"], {}], prompt_length: [["Medium"], {}] },
    presets: [{ id: "general_director", label: "General Director" }],
    engine: { profiles: [], noEngine: true },
    job: { kind: "builder", result: { planning_status: "planned" } },
  }));
  assert.doesNotMatch(markup, /Builder planning|builder-planning-help|Supporting scene planning|>Planning</);
  for (const label of ["Describe your idea", "Target model", "Creativity", "Prompt length"]) {
    assert.ok(markup.includes(`aria-label="${label}"`), `missing ${label}`);
  }
});

test("MiniMax retains its Planning control", async () => {
  const { PlanningSelect } = await import(await jsxModuleUrl(new URL("./workflows/WorkflowControls.jsx", import.meta.url)));
  const markup = renderToStaticMarkup(createElement(PlanningSelect, { video: true, value: "Auto", onChange() {} }));
  assert.match(markup, /aria-label="MiniMax planning"/);
  assert.match(markup, /<option selected="">Auto<\/option>/);
});
