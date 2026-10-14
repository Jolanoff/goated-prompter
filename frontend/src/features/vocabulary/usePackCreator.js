import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../../api.js";
import { newPackDocument } from "./creatorModel.js";

const base = "/vocabulary/creator";

export function usePackCreator(visible, onInstalled) {
  const [schemas, setSchemas] = useState(null);
  const [references, setReferences] = useState({ entries: [], categories: [], problems: [] });
  const [drafts, setDrafts] = useState([]);
  const [document, setDocument] = useState(newPackDocument);
  const [saved, setSaved] = useState(null);
  const [savedText, setSavedText] = useState(() => JSON.stringify(newPackDocument()));
  const [readOnly, setReadOnly] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [validation, setValidation] = useState(null);
  const [pending, setPending] = useState(null);
  const [generation, setGeneration] = useState(0);
  const [edition, setEdition] = useState(0);
  const active = useRef(false);
  const text = JSON.stringify(document);
  const dirty = text !== savedText;

  useEffect(() => {
    if (!visible) return;
    const controller = new AbortController();
    setLoading(true); setError("");
    const get = (path) => api(`${base}/${path}`, undefined, "GET", { signal: controller.signal });
    Promise.all([get("schemas"), get("references"), get("drafts")]).then(([schema, refs, records]) => {
      if (!controller.signal.aborted) { setSchemas(schema); setReferences(refs); setDrafts(records.drafts); }
    }).catch((failure) => { if (!controller.signal.aborted) setError(failure.message); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [visible, generation]);

  useEffect(() => {
    if (!dirty) return;
    const warn = (event) => { event.preventDefault(); event.returnValue = ""; };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  function change(next) { setDocument(next); setValidation(null); setNotice(""); }
  function adopt(record, readonly = false, isDraft = false) {
    setEdition((value) => value + 1);
    setDocument(record.document); setSaved(isDraft ? { id: record.id, revision: record.revision } : null);
    setSavedText(isDraft || readonly ? JSON.stringify(record.document) : ""); setReadOnly(readonly); setValidation(null); setNotice("");
  }
  async function run(operation) {
    if (active.current) return;
    active.current = true; setBusy(true); setError(""); setNotice("");
    try { return await operation(); }
    catch (failure) { setError(failure.message); }
    finally { active.current = false; setBusy(false); }
  }
  function confirm(label, action) { setPending({ label, action }); }
  function replace(label, action) { if (dirty) confirm(`Discard unsaved changes and ${label}?`, action); else action(); }
  function startNew() { replace("create a new pack", () => { adopt({ document: newPackDocument() }); setSavedText(JSON.stringify(newPackDocument())); }); }
  function openDraft(id) {
    replace("open this draft", () => run(async () => { adopt(await api(`${base}/drafts/${id}`), false, true); }));
  }
  function openPack(pack) {
    replace("open this pack", () => run(async () => {
      const data = await api(`${base}/source/${encodeURIComponent(pack.id)}?origin=${pack.origin}`);
      adopt(data, data.read_only);
    }));
  }
  function importZIP(file) {
    if (!file) return;
    replace("import this ZIP", () => run(async () => {
      const data = await api(`${base}/import`, undefined, "POST", { headers: { "Content-Type": "application/zip" }, body: file });
      adopt(data, data.read_only);
    }));
  }
  function save() { return run(async () => {
    const data = await api(`${base}/drafts${saved ? `/${saved.id}` : ""}`, { document, ...(saved ? { revision: saved.revision } : {}) }, saved ? "PUT" : "POST");
    setSaved({ id: data.id, revision: data.revision }); setSavedText(JSON.stringify(data.document));
    setDrafts((await api(`${base}/drafts`)).drafts); setNotice("Draft saved. Installed packs are unchanged.");
  }); }
  function validate() { return run(async () => { const data = await api(`${base}/validate`, { document }); setValidation(data); }); }
  function preview(sample) { return run(async () => { const data = await api(`${base}/preview`, { document, sample }); setValidation(data); }); }
  function exportZIP() { return run(async () => {
    const validation = await api(`${base}/validate`, { document }); setValidation(validation);
    if (!validation.valid) return;
    const response = await fetch(`/api${base}/export`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ document }) });
    if (!response.ok) { const failure = await response.json(); throw new Error(failure.error || "Export failed."); }
    const url = URL.createObjectURL(await response.blob());
    const anchor = window.document.createElement("a"); anchor.href = url; anchor.download = `${document.manifest.id}.zip`; anchor.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000); setNotice("Valid pack exported. Nothing was installed.");
  }); }
  function install(updateId = null) {
    confirm(updateId ? `Update installed pack ${updateId} with this draft? Its enabled setting will be preserved.` : `Install ${document.manifest.id}? This will make the completed pack available to Dataset.`, () => run(async () => {
      const check = await api(`${base}/validate`, { document }); setValidation(check); if (!check.valid) return;
      await api(`${base}/install`, { document, confirmed: true, ...(updateId ? { update_id: updateId } : {}) });
      setNotice(updateId ? "Installed pack updated." : "Pack installed."); await onInstalled(); setGeneration((value) => value + 1);
    }));
  }
  const accept = useCallback(() => { const action = pending?.action; setPending(null); action?.(); }, [pending]);
  return { schemas, references, drafts, document, change, readOnly, saved, dirty, loading, busy, error, notice, validation, edition,
    pending, accept, cancel: () => setPending(null), confirm, startNew, openDraft, openPack, importZIP, save, validate, preview, exportZIP, install,
    reload: () => setGeneration((value) => value + 1) };
}
