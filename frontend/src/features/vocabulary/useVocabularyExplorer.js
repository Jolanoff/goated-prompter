import { useEffect, useRef, useState } from "react";
import { api } from "../../api.js";

export const packKey = (pack) => `${pack.origin}:${pack.id}`;
export const PREVIEW_SCENES = 6;
const MAX_SEED = 2147483647;

const lines = (text) => String(text || "").split("\n").map((line) => line.trim()).filter(Boolean);

// The sample stands for a confirmed brief: its request, characters, what may vary and what to avoid.
export function inspectionPayload(sample) {
  const seed = Number.parseInt(String(sample.seed ?? "0"), 10);
  return { request: sample.request, nsfw: sample.nsfw, characters: lines(sample.characters),
    randomized: String(sample.randomized || ""), avoid: lines(sample.avoid),
    seed: Number.isFinite(seed) && seed >= 0 ? Math.min(seed, MAX_SEED) : 0, scenes: PREVIEW_SCENES };
}

export function useVocabularyExplorer({ visible, packs, revision }) {
  const [selectedPack, setSelectedPack] = useState("");
  const [filters, setFilters] = useState({ q: "", category: "", rating: "", sort: "name" });
  const [catalogue, setCatalogue] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [entry, setEntry] = useState(null);
  const [detail, setDetail] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState("");
  const [sample, setSample] = useState({ request: "", characters: "", nsfw: false, randomized: "", avoid: "", seed: "0" });
  const [result, setResult] = useState(null);
  const [inspecting, setInspecting] = useState(false);
  const [inspectionError, setInspectionError] = useState("");
  const inspection = useRef(null);
  const [refresh, setRefresh] = useState(0);
  const pack = packs.find((item) => packKey(item) === selectedPack) || packs[0];
  const id = pack?.id, origin = pack?.origin;
  const { q, category, rating, sort } = filters;

  useEffect(() => {
    if (!visible || !id) return;
    const controller = new AbortController();
    setLoading(true); setError("");
    const params = new URLSearchParams({ origin, q, category, rating, sort });
    const timer = setTimeout(() => api(`/vocabulary/packs/${encodeURIComponent(id)}/entries?${params}`, undefined, "GET", { signal: controller.signal })
      .then((data) => { if (!controller.signal.aborted) setCatalogue(data); })
      .catch((failure) => { if (!controller.signal.aborted) { setError(failure.message); setCatalogue(null); } })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); }), q ? 150 : 0);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [visible, id, origin, q, category, rating, sort, revision, refresh]);

  useEffect(() => {
    if (!visible || !entry) return;
    const controller = new AbortController();
    setDetail(null); setDetailLoading(true); setDetailError("");
    const params = new URLSearchParams(entry.origin ? { origin: entry.origin } : {});
    api(`/vocabulary/entries/${encodeURIComponent(entry.id)}?${params}`, undefined, "GET", { signal: controller.signal })
      .then((data) => { if (!controller.signal.aborted) setDetail(data); })
      .catch((failure) => { if (!controller.signal.aborted) setDetailError(failure.message); })
      .finally(() => { if (!controller.signal.aborted) setDetailLoading(false); });
    return () => controller.abort();
  }, [visible, entry, revision, refresh]);

  useEffect(() => {
    inspection.current?.abort(); setResult(null); setInspecting(false);
    return () => inspection.current?.abort();
  }, [revision]);

  function clearEntry() { setEntry(null); setDetail(null); setDetailError(""); setDetailLoading(false); }
  function selectPack(key) { setSelectedPack(key); setFilters({ q: "", category: "", rating: "", sort: "name" }); clearEntry(); setCatalogue(null); }
  function filter(patch) { setFilters((current) => ({ ...current, ...patch })); clearEntry(); }
  function navigate(target) {
    const nextPack = target.origin ? `${target.origin}:${target.id.split(":")[0]}` : "";
    if (nextPack !== `${origin}:${id}`) {
      setSelectedPack(nextPack); setFilters({ q: "", category: "", rating: "", sort: "name" }); setCatalogue(null);
    }
    setEntry(target);
  }
  function editSample(patch) {
    inspection.current?.abort(); setInspecting(false); setResult(null); setInspectionError("");
    setSample((current) => ({ ...current, ...patch }));
  }
  async function inspect() {
    if (inspecting || !sample.request.trim()) return;
    const controller = new AbortController(); inspection.current = controller;
    setInspecting(true); setInspectionError(""); setResult(null);
    try {
      const data = await api("/vocabulary/retrieve", inspectionPayload(sample), "POST", { signal: controller.signal });
      if (!controller.signal.aborted) setResult(data);
    } catch (failure) { if (!controller.signal.aborted) setInspectionError(failure.message); }
    finally { if (!controller.signal.aborted) setInspecting(false); }
  }
  return { pack, catalogue, loading, error, filters, filter, selectPack, entry, detail, detailLoading, detailError,
    navigate, clearEntry, sample, editSample, result, inspecting, inspectionError, inspect,
    reload: () => setRefresh((current) => current + 1) };
}
