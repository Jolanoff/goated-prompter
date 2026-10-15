import { useCallback, useEffect, useState } from "react";
import { api } from "../../api.js";
import { defaultPackSelection, packChoices, selectionProblem, sortedIds } from "../vocabulary/packSelection.js";

// The Dataset tab's own pack choice for its next run. Remembered in this browser only as a convenience;
// each confirmed run records its resolved selection on the server, which is what that run uses from then on.
export const PACKS_KEY = "goated-prompter.dataset-vocabulary-packs.v1";

export function readStoredPacks(storage = globalThis.localStorage) {
  try {
    const value = JSON.parse(storage?.getItem(PACKS_KEY) || "null");
    return Array.isArray(value?.selected) && value.selected.every((id) => typeof id === "string") ? sortedIds(value.selected) : null;
  } catch { return null; }
}

export function writeStoredPacks(selected, storage = globalThis.localStorage) {
  try { storage?.setItem(PACKS_KEY, JSON.stringify({ selected: sortedIds(selected) })); } catch { /* per-browser convenience only */ }
}

export function useDatasetPacks(visible) {
  const [packs, setPacks] = useState(null);
  const [stored, setStored] = useState(() => readStoredPacks());
  const [error, setError] = useState("");
  const reload = useCallback(() => api("/vocabulary/packs").then((data) => { setPacks(data.packs); setError(""); })
    .catch((failure) => setError(`Could not load vocabulary packs. ${failure.message}`)), []);
  useEffect(() => { if (visible) void reload(); }, [visible, reload]);
  const selected = stored ?? (packs ? defaultPackSelection(packs) : null);
  function choose(next) {
    setStored(sortedIds(next));
    writeStoredPacks(next);
  }
  const problem = packs && selected ? selectionProblem(packChoices(packs, selected)) : "";
  return { packs: packs || [], selected: selected || [], ready: !!packs && !!selected && !problem, loading: !packs && !error,
    error, problem, choose, reload };
}

/** A stored run's recorded selection and how today's packs compare, from the run store (read-only). */
export function useRunPacks(runId) {
  const [value, setValue] = useState(null);
  useEffect(() => {
    if (!runId) { setValue(null); return; }
    const controller = new AbortController();
    api(`/workspace/dataset/v2/runs/${encodeURIComponent(runId)}/packs`, undefined, "GET", { signal: controller.signal })
      .then((data) => { if (!controller.signal.aborted) setValue({ runId, packs: data.packs, status: data.status, error: "" }); })
      .catch((failure) => { if (!controller.signal.aborted) setValue({ runId, packs: null, status: null, error: failure.message }); });
    return () => controller.abort();
  }, [runId]);
  return value?.runId === runId ? value : null;
}
