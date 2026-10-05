import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api.js";
import { createBuilderSaver } from "../storage.js";

/** One serialized autosave stream per workflow; never rehydrate on write acknowledgements. */
export function useWorkflowSettings(operation) {
  const [record, setRecord] = useState(null);
  const [draft, setDraft] = useState(null);
  const [status, setStatus] = useState("Loading");
  const [error, setError] = useState("");
  const [working, setWorking] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [conflict, setConflict] = useState(false);
  const latest = useRef(null);
  const currentDraft = useRef(null);
  const mounted = useRef(true);
  const loading = useRef(0);
  const instructionWrite = useRef(false);
  const saver = useRef(null);
  const editSequence = useRef(0);
  const refreshSequence = useRef(0);
  const path = `/workspace/settings/${operation}`;
  if (!saver.current) saver.current = createBuilderSaver(async (next, keepalive) => {
    try {
      const saved = await api(path, { revision: latest.current.revision, draft: next }, "PUT", { keepalive });
      latest.current = saved;
      if (mounted.current) setRecord(saved);
    } catch (err) {
      if (err.status === 409 && mounted.current) setConflict(true);
      throw err;
    }
  }, (nextStatus, message) => {
    if (mounted.current) { setStatus(nextStatus); setError(message); }
  });

  const load = useCallback(async () => {
    const attempt = ++loading.current;
    setWorking(true);
    try {
      const saved = await api(path);
      if (!mounted.current || loading.current !== attempt) return;
      latest.current = saved;
      currentDraft.current = saved.draft;
      saver.current.hydrate(saved.draft);
      setRecord(saved);
      setDraft(saved.draft);
      setConflict(false);
      setError("");
    } catch (err) {
      if (mounted.current) { setError(err.message); setStatus("Load failed"); }
    } finally { if (mounted.current && loading.current === attempt) setWorking(false); }
  }, [path]);

  useEffect(() => {
    mounted.current = true;
    const loadSequence = loading;
    load();
    const leave = () => { saver.current.flush(true).catch(() => {}); };
    window.addEventListener("pagehide", leave);
    return () => {
      mounted.current = false;
      loadSequence.current++;
      window.removeEventListener("pagehide", leave);
      saver.current.dispose();
    };
  }, [load]);

  const update = useCallback((patch) => {
    if (!currentDraft.current) return;
    editSequence.current++;
    const next = { ...currentDraft.current, ...patch };
    currentDraft.current = next;
    setDraft(next);
    saver.current.stage(next);
  }, []);

  const refreshGenerated = useCallback(async () => {
    const sequence = editSequence.current;
    const attempt = ++refreshSequence.current;
    // Job completion can advance the server revision before its GET arrives.
    // Keep editable controls locked until the matching draft/revision is loaded.
    setRefreshing(true);
    try {
      await saver.current.flush();
      const saved = await api(path);
      // A completed old job must never replace a newer unsaved edit.
      if (!mounted.current || sequence !== editSequence.current || attempt !== refreshSequence.current) return;
      latest.current = saved;
      currentDraft.current = saved.draft;
      saver.current.hydrate(saved.draft);
      setRecord(saved);
      setDraft(saved.draft);
    } finally {
      if (mounted.current && attempt === refreshSequence.current) setRefreshing(false);
    }
  }, [path]);

  async function saveInstructions(instructions, reset = false) {
    if (instructionWrite.current || !latest.current) return false;
    instructionWrite.current = true;
    setWorking(true);
    setError("");
    try {
      await saver.current.flush();
      const saved = await api(`${path}/instructions`, { revision: latest.current.revision,
        action: reset ? "reset" : "save", ...(reset ? {} : { instructions }) });
      latest.current = saved;
      setRecord(saved);
      return true;
    } catch (err) {
      if (err.status === 409 && !err.activeJob) setConflict(true);
      setError(err.message);
      return false;
    } finally { instructionWrite.current = false; setWorking(false); }
  }

  async function reload() {
    // Settle in-flight writes, but never submit unsaved edits the user chose to discard.
    setWorking(true);
    await saver.current.discard();
    await load();
  }

  return { record, draft, update, status, error, working: working || refreshing, conflict, reload, saveInstructions, refreshGenerated,
    revision: () => latest.current?.revision, flush: () => saver.current.flush() };
}
