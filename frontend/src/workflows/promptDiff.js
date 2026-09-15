/** Bounded word diff, with a prefix/suffix fallback for huge prompts. */
export function promptDiff(before, after) {
  const a = before.match(/\s+|[^\s]+/g) || [];
  const b = after.match(/\s+|[^\s]+/g) || [];
  let start = 0;
  while (start < a.length && start < b.length && a[start] === b[start]) start++;
  let endA = a.length, endB = b.length;
  while (endA > start && endB > start && a[endA - 1] === b[endB - 1]) { endA--; endB--; }
  const parts = [];
  const add = (kind, text) => {
    if (!text) return;
    if (parts.at(-1)?.kind === kind) parts.at(-1).text += text;
    else parts.push({ kind, text });
  };
  add("same", a.slice(0, start).join(""));
  const x = a.slice(start, endA), y = b.slice(start, endB);
  // At most ~1 MB of typed-array cells; never quadratic work on large documents.
  if ((x.length + 1) * (y.length + 1) > 250000) {
    add("removed", x.join(""));
    add("added", y.join(""));
  } else {
    const width = y.length + 1;
    const table = new Uint32Array((x.length + 1) * width);
    for (let i = x.length - 1; i >= 0; i--)
      for (let j = y.length - 1; j >= 0; j--)
        table[i * width + j] = x[i] === y[j] ? table[(i + 1) * width + j + 1] + 1
          : Math.max(table[(i + 1) * width + j], table[i * width + j + 1]);
    let i = 0, j = 0;
    while (i < x.length || j < y.length) {
      if (i < x.length && j < y.length && x[i] === y[j]) { add("same", x[i++]); j++; }
      else if (j < y.length && (i === x.length || table[i * width + j + 1] > table[(i + 1) * width + j])) add("added", y[j++]);
      else add("removed", x[i++]);
    }
  }
  add("same", a.slice(endA).join(""));
  return parts;
}
