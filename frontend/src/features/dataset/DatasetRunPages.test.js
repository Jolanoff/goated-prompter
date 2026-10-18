import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { Children } from "react";
import { transformWithEsbuild } from "vite";

async function loadRunPrompts() {
  const sourceUrl = new URL("./DatasetRunPages.jsx", import.meta.url);
  const { code } = await transformWithEsbuild(await readFile(sourceUrl, "utf8"), sourceUrl.pathname,
    { loader: "jsx", jsx: "automatic", sourcemap: false });
  const linked = code.replace(/from (["'])([^"']+)\1/g, (_match, _quote, specifier) =>
    `from ${JSON.stringify(specifier.startsWith(".") ? new URL(specifier, sourceUrl).href : import.meta.resolve(specifier))}`);
  return (await import(`data:text/javascript;base64,${Buffer.from(linked).toString("base64")}`)).RunPrompts;
}

function buttons(element) {
  if (!element?.props) return [];
  return [...(element.type === "button" ? [element] : []),
    ...Children.toArray(element.props.children).flatMap(buttons)];
}

for (const { name, prompts, expected } of [
  { name: "multiple prompts", prompts: ["First prompt.", "Second prompt."], expected: "First prompt.\nSecond prompt." },
  { name: "multiline prompts", prompts: [" First\r\n\r\nprompt. ", "Second\nprompt."], expected: "First prompt.\nSecond prompt." },
  { name: "one prompt", prompts: ["Only prompt."], expected: "Only prompt." },
]) {
  test(`completed Dataset Copy all has no blank lines for ${name} and leaves TXT unchanged`, async () => {
    const RunPrompts = await loadRunPrompts();
    const run = { status: "completed", result: { complete: true, scenes: [],
      prompts: prompts.map((prompt, index) => ({ index: index + 1, prompt, trigger_ok: true })) } };
    const before = structuredClone(run);
    let copied;
    let downloaded;
    const page = RunPrompts({ run, onCopy: (text) => { copied = text; },
      onDownload: (...args) => { downloaded = args; } });
    const controls = buttons(page);
    controls.find((button) => Children.toArray(button.props.children).includes("Copy all")).props.onClick();
    assert.equal(copied, expected);
    controls.find((button) => Children.toArray(button.props.children).includes("TXT")).props.onClick();
    assert.deepEqual(downloaded, ["dataset-prompts.txt", prompts.join("\n\n"), "text/plain;charset=utf-8"]);
    assert.deepEqual(run, before);
  });
}
