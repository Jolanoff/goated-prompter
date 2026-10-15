// Per-run Vocabulary pack selection (Phase 2). The server resolves, fingerprints and records the selection
// (vocabulary/packs.py resolve_selection); this module only prepares what the selector shows and sends.
// Nothing here changes the global Pack Manager state.

export const sortedIds = (ids) => [...new Set(ids)].sort();

const usable = (pack) => !!pack?.valid && !pack.problems?.length;

/** The optional packs a new selection starts from: those valid and enabled globally. Core is always added by the server. */
export function defaultPackSelection(packs) {
  return sortedIds((packs || []).filter((pack) => !pack.mandatory && pack.enabled && usable(pack)).map((pack) => pack.id));
}

export function togglePack(selected, id) {
  return sortedIds(selected.includes(id) ? selected.filter((item) => item !== id) : [...selected, id]);
}

/**
 * One row per discovered pack, plus a row for each selected id that is no longer installed.
 * role: core | selected | dependency | off (a dependency is required by a selected pack but not chosen itself).
 * status: ok | invalid | blocked (a requirement is missing or invalid) | unavailable (selected but not installed).
 */
export function packChoices(packs, selected) {
  const known = new Map();
  for (const pack of packs || []) if (!known.has(pack.id)) known.set(pack.id, pack);
  const chosen = new Set(selected);
  const dependencies = new Set();
  const queue = [...known.values()].filter((pack) => pack.mandatory).map((pack) => pack.id).concat(selected);
  for (const seen = new Set(); queue.length;) {
    const id = queue.shift();
    if (seen.has(id)) continue;
    seen.add(id);
    for (const required of Object.keys(known.get(id)?.requires || {}).sort()) {
      if (!chosen.has(required) && !known.get(required)?.mandatory) dependencies.add(required);
      queue.push(required);
    }
  }
  const rows = [...known.values()].map((pack) => {
    const missing = Object.keys(pack.requires || {}).sort().filter((id) => !usable(known.get(id)));
    return { id: pack.id, name: pack.name || pack.id, version: pack.version, origin: pack.origin,
      mandatory: !!pack.mandatory, enabledGlobally: !!pack.enabled, problems: pack.problems || [], missing,
      role: pack.mandatory ? "core" : chosen.has(pack.id) ? "selected" : dependencies.has(pack.id) ? "dependency" : "off",
      status: missing.length ? "blocked" : usable(pack) ? "ok" : "invalid" };
  });
  for (const id of [...chosen].sort()) {
    if (!known.has(id)) rows.push({ id, name: id, version: null, origin: null, mandatory: false, enabledGlobally: false,
      problems: [], missing: [], role: "selected", status: "unavailable" });
  }
  for (const id of [...dependencies].sort()) {
    if (!known.has(id)) rows.push({ id, name: id, version: null, origin: null, mandatory: false, enabledGlobally: false,
      problems: [], missing: [], role: "dependency", status: "unavailable" });
  }
  return rows;
}

/** Why this selection cannot be used, or "" when every participating pack is usable. */
export function selectionProblem(rows) {
  const broken = rows.filter((row) => row.role !== "off" && row.status !== "ok");
  if (!broken.length) return "";
  return `These packs cannot be used: ${broken.map((row) => `${row.name} (${statusLabels[row.status]})`).join(", ")}. Deselect them or fix them in Vocabulary › Packs.`;
}

export const statusLabels = { ok: "Available", invalid: "Invalid", blocked: "Dependency missing or invalid", unavailable: "Not installed" };
export const roleLabels = { core: "Required", selected: "Selected", dependency: "Added as dependency", off: "Not used" };

/**
 * What a stored run recorded, for display: never today's global selection.
 * recorded is the run's `packs` field ({recorded: false} for schema 1 runs); status is {exact, drift, disabled_globally}.
 */
export function recordedPackSummary(recorded, status) {
  if (!recorded || recorded.recorded === false) {
    return { state: "not_recorded", label: "Not recorded", rows: [],
      note: "This run was created before pack selections were saved. Its packs are unknown and are not guessed from current settings." };
  }
  if (!recorded.enabled) return { state: "off", label: "Vocabulary off", rows: [], note: "This run used no vocabulary packs." };
  const drift = status?.drift || [];
  const disabled = new Set(status?.disabled_globally || []);
  const rows = recorded.packs.map((pack) => ({ ...pack, drift: drift.filter((item) => item.id === pack.id),
    disabledGlobally: disabled.has(pack.id) }));
  const exact = status ? status.exact : null;
  return { state: exact === false ? "drift" : exact ? "exact" : "unknown", rows,
    label: exact === false ? "Packs changed since this run" : exact ? "Recorded packs unchanged" : "Recorded packs",
    note: exact === false ? "The installed packs no longer match this run's recorded content. Nothing falls back to other versions." : "" };
}

export const shortFingerprint = (value) => String(value || "").replace(/^sha256:/, "").slice(0, 12);
