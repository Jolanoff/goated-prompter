import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../../api.js";

export function useVocabularyPacks(visible) {
  const [snapshot, setSnapshot] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [removing, setRemoving] = useState(null);
  const [target, setTarget] = useState(null);
  const [file, setFile] = useState(null);
  const pending = useRef(false);

  const reload = useCallback(async () => {
    if (pending.current) return;
    pending.current = true;
    setLoading(true);
    setError("");
    try { setSnapshot(await api("/vocabulary/packs")); }
    catch (failure) { setError(failure.message); }
    finally { pending.current = false; setLoading(false); }
  }, []);
  useEffect(() => { if (visible) reload(); }, [visible, reload]);

  async function mutate(action, message) {
    if (pending.current) return false;
    pending.current = true;
    setSaving(true);
    setError("");
    setNotice("");
    try {
      setSnapshot(await action());
      setNotice(message);
      setRemoving(null);
      return true;
    } catch (failure) {
      setError(failure.message);
      return false;
    } finally { pending.current = false; setSaving(false); }
  }

  function chooseUpdate(pack) { setTarget(pack); setFile(null); setError(""); }

  async function upload() {
    if (!file) return;
    if (snapshot && file.size > snapshot.max_archive_bytes) {
      setError(`Choose a ZIP no larger than ${snapshot.max_archive_bytes / (1024 * 1024)} MB.`);
      return;
    }
    const path = `/vocabulary/packs${target ? `/${encodeURIComponent(target.id)}` : ""}`;
    const success = await mutate(() => api(path, undefined, target ? "PUT" : "POST", {
      headers: { "Content-Type": "application/zip" }, body: file,
    }), target ? `${target.name || target.id} updated. Changes apply to the next Dataset run.`
      : "Pack installed. Available for the next Dataset run.");
    if (success) { setFile(null); setTarget(null); }
    return success;
  }

  return { snapshot, loading, saving, error, notice, removing, target, file, reload, upload,
    setFile, chooseUpdate, setRemoving,
    toggle: (pack) => mutate(() => api(`/vocabulary/packs/${encodeURIComponent(pack.id)}`,
      { enabled: !pack.enabled }, "PATCH"), `${pack.name || pack.id} ${pack.enabled ? "disabled" : "enabled"}. Changes apply to the next Dataset run.`),
    remove: (pack) => mutate(() => api(`/vocabulary/packs/${encodeURIComponent(pack.id)}`, undefined, "DELETE"),
      `${pack.name || pack.id} removed.`) };
}
