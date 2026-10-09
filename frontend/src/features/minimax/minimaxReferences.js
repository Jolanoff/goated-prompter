import { referenceLimits } from "./options.js";

export function parseReferences(text) {
  const references = [], invalid = [];
  for (const match of text.matchAll(/<(image|video|audio)(\d+)>/gi)) {
    const kind = match[1].toLowerCase(), number = Number(match[2]);
    if (number < 1 || number > referenceLimits[kind] || match[2].startsWith("0")) invalid.push(match[0]);
    else if (!references.includes(`${kind}${number}`)) references.push(`${kind}${number}`);
  }
  return { references, invalid };
}

export function nextReference(kind, references) {
  if (references.length >= 12) return null;
  for (let number = 1; number <= referenceLimits[kind]; number++) {
    if (!references.includes(`${kind}${number}`)) return `${kind}${number}`;
  }
  return null;
}

export function insertReference(text, token, start = text.length, end = start) {
  const before = text.slice(0, start), after = text.slice(end);
  const prefix = before && !/\s$/.test(before) ? " " : "";
  const suffix = after && !/^[\s.,;:!?)]/.test(after) ? " " : "";
  const inserted = `${prefix}<${token}>${suffix}`;
  return { text: before + inserted + after, cursor: before.length + inserted.length };
}

export function parseShots(text) {
  const shots = [], invalid = [];
  for (const match of text.matchAll(/<shot[^>]*>/gi)) {
    const token = /^<shot(\d+)>$/i.exec(match[0]);
    if (!token || token[1].startsWith("0") || !Number.isSafeInteger(Number(token[1])) || Number(token[1]) < 1) invalid.push(match[0]);
    else shots.push(`shot${Number(token[1])}`);
  }
  return { shots, invalid, ordered: shots.every((shot, index) => shot === `shot${index + 1}`) };
}

export function nextShot(text) {
  const { shots } = parseShots(text);
  let number = 1;
  while (shots.includes(`shot${number}`)) number++;
  return `shot${number}`;
}

export function insertShot(text, token, start = text.length, end = start) {
  const before = text.slice(0, start), after = text.slice(end);
  const prefix = before && !/\n$/.test(before) ? "\n" : "";
  const suffix = after && !/^\s/.test(after) ? "\n" : " ";
  const inserted = `${prefix}<${token}>${suffix}`;
  return { text: before + inserted + after, cursor: before.length + inserted.length };
}
