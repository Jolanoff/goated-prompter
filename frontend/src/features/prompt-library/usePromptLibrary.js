import { useCallback, useEffect, useEffectEvent, useRef, useState } from "react";
import { api } from "../../api.js";

export function usePromptLibrary({ visible, initialTarget, onNotice }) {
  const [target, setTarget] = useState(initialTarget);
  const [library, setLibrary] = useState(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [editor, setEditor] = useState(null);
  const [draft, setDraft] = useState("");
  const [deleting, setDeleting] = useState(null);
  const requestId = useRef(0);
  const writing = useRef(false);
  const dirty = editor !== null && draft !== editor.original;

  const load = useCallback(async () => {
    const id = ++requestId.current;
    setLoading(true);
    setError("");
    try {
      const result = await api(`/prompt-library?target=${encodeURIComponent(target)}`);
      if (id === requestId.current) setLibrary(result);
    } catch (err) {
      if (id === requestId.current) {
        setLibrary(null);
        setError(err.message);
      }
    } finally {
      if (id === requestId.current) setLoading(false);
    }
  }, [target]);

  const loadOnOpen = useEffectEvent(() => {
    if (editor === null && deleting === null) load();
  });
  useEffect(() => {
    if (visible) loadOnOpen();
  }, [visible, target]);
  useEffect(() => () => { requestId.current += 1; }, []);
  useEffect(() => {
    if (!dirty) return undefined;
    const warn = (event) => { event.preventDefault(); event.returnValue = ""; };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  function discard() {
    return !dirty || window.confirm("Discard your unsaved library prompt?");
  }

  function selectTarget(next) {
    if (writing.current || next === target || !discard()) return;
    requestId.current += 1;
    setLibrary(null);
    setEditor(null);
    setDeleting(null);
    setDraft("");
    setTarget(next);
  }

  function edit(index = null) {
    if (writing.current || !library || !discard()) return;
    const original = index === null ? "" : library.prompts[index];
    setEditor({ index, original });
    setDraft(original);
    setDeleting(null);
    setError("");
  }

  function cancel() {
    if (writing.current || !discard()) return;
    setEditor(null);
    setDraft("");
  }

  function requestDelete(index) {
    if (writing.current || !discard()) return;
    setEditor(null);
    setDraft("");
    setDeleting(index);
    setError("");
  }

  function reload() {
    if (writing.current || !discard()) return;
    setEditor(null);
    setDraft("");
    setDeleting(null);
    load();
  }

  async function write(remove = false) {
    if (writing.current || loading || !library || (!remove && (!editor || !draft.trim()))) return;
    writing.current = true;
    setSaving(true);
    setError("");
    try {
      const result = await api(`/prompt-library?target=${encodeURIComponent(target)}`, {
        revision: library.revision,
        index: remove ? deleting : editor.index,
        ...(!remove && { prompt: draft }),
      }, remove ? "DELETE" : editor.index === null ? "POST" : "PUT");
      setLibrary(result);
      setEditor(null);
      setDraft("");
      setDeleting(null);
      onNotice(remove ? "Library prompt deleted." : "Library prompt saved.");
    } catch (err) {
      setError(`${err.message}${remove ? "" : " Draft kept in this tab."}`);
    } finally {
      writing.current = false;
      setSaving(false);
    }
  }

  return { target, library, loading, saving, error, editor, draft, dirty, deleting,
    setDraft, selectTarget, edit, cancel, reload, requestDelete,
    cancelDelete: () => setDeleting(null), save: () => write(), remove: () => write(true) };
}
