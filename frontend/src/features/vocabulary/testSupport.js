import { readFile } from "node:fs/promises";
import { transformWithEsbuild } from "vite";

export async function compileView(source) {
  const { code } = await transformWithEsbuild(await readFile(source, "utf8"), source.pathname,
    { loader: "jsx", jsx: "automatic", sourcemap: false });
  let linked = code;
  for (const [statement, , specifier] of code.matchAll(/from (["'])([^"']+)\1/g)) {
    const target = specifier.startsWith(".") ? new URL(specifier, source).href : import.meta.resolve(specifier);
    const resolved = specifier.endsWith(".jsx") ? await compileView(new URL(target)) : target;
    linked = linked.replace(statement, `from ${JSON.stringify(resolved)}`);
  }
  return `data:text/javascript;base64,${Buffer.from(linked).toString("base64")}`;
}
