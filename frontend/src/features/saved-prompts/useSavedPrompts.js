import { useEffect, useRef, useState } from "react";
import { api } from "../../api.js";
import { loadSaved, SAVED_KEY } from "../../storage.js";

/** Saved prompts on the local JSON file, legacy browser import and the save dialog. */
export function useSavedPrompts({ setError, setNotice }) {
  const [saved, setSaved] = useState([]);
  const [storageReady, setStorageReady] = useState(false);
  const [storageWarning, setStorageWarning] = useState("");
  const [storageError, setStorageError] = useState("");
  const [storageReload, setStorageReload] = useState(0);
  const [promptsBusy, setPromptsBusy] = useState(false);
  const [dialogError, setDialogError] = useState("");
  const [saveKind, setSaveKind] = useState(null);
  const [saveName, setSaveName] = useState("");
  const [saveText, setSaveText] = useState("");
  const [saveTarget, setSaveTarget] = useState("Generic");
  const [dialogBusy, setDialogBusy] = useState(false);
  const dialogRef = useRef(null);
  const saveNameRef = useRef(null);
  const pendingPromptRef = useRef(null);
  const saveSourceRef = useRef(null);

  useEffect(() => {
    if (!storageReload) return;
    let disposed = false;
    async function loadPrompts() {
      setStorageReady(false);
      setStorageError("");
      setStorageWarning("");
      try {
        let data = await api("/prompts");
        if (disposed) return;
        if (!Array.isArray(data.prompts))
          throw new Error("Invalid saved prompts response.");
        try {
          const storage = window.localStorage;
          const legacy = loadSaved(storage);
          if (legacy.length) {
            const imported = await api("/prompts/import", { prompts: legacy });
            if (disposed) return;
            // Only remove the browser copy after every field is confirmed on disk.
            if (
              !Array.isArray(imported.prompts) ||
              !legacy.every((record) =>
                imported.prompts.some(
                  (item) =>
                    Object.keys(item).length === Object.keys(record).length &&
                    Object.keys(record).every(
                      (key) =>
                        Object.hasOwn(item, key) && item[key] === record[key],
                    ),
                ),
              )
            )
              throw new Error(
                "The server did not confirm the exact imported records.",
              );
            data = imported;
            storage.removeItem(SAVED_KEY);
          }
        } catch (err) {
          if (disposed) return;
          setStorageWarning(
            `Browser migration could not finish. Browser data has been kept; server prompts remain available. ${err.message}`,
          );
        }
        if (disposed) return;
        setSaved(data.prompts);
        setStorageReady(true);
      } catch (err) {
        if (!disposed)
          setStorageError(
            `Could not load saved prompts from the local JSON file. ${err.message}`,
          );
      }
    }
    loadPrompts();
    return () => {
      disposed = true;
    };
  }, [storageReload]);

  useEffect(() => {
    if (saveKind) {
      dialogRef.current?.showModal();
      saveNameRef.current?.focus();
    }
    else dialogRef.current?.close();
  }, [saveKind]);

  function reload() {
    setStorageReload((value) => value + 1);
  }

  async function deletePrompt(record) {
    if (!storageReady || promptsBusy || dialogBusy) return;
    if (!window.confirm(`Delete "${record.title}"? This cannot be undone.`))
      return;
    setPromptsBusy(true);
    setError("");
    setNotice("");
    try {
      const data = await api(
        `/prompts/${encodeURIComponent(record.id)}`,
        {},
        "DELETE",
      );
      setSaved(data.prompts);
      setNotice("Prompt deleted from the local JSON file.");
    } catch (err) {
      setError(`Could not delete prompt. ${err.message}`);
    } finally {
      setPromptsBusy(false);
    }
  }

  function requestPromptSave(text, target, title) {
    if (!text.trim() || !storageReady || promptsBusy || dialogBusy) return;
    saveSourceRef.current = { prompt: text, target };
    pendingPromptRef.current = null;
    setDialogError("");
    setSaveKind("prompt");
    setSaveName(title.slice(0, 70));
  }

  function requestNewPrompt(target) {
    if (!storageReady || promptsBusy || dialogBusy || saveKind) return;
    saveSourceRef.current = null;
    pendingPromptRef.current = null;
    setDialogError("");
    setSaveName("");
    setSaveText("");
    setSaveTarget(target);
    setSaveKind("new");
  }

  async function save(event) {
    event.preventDefault();
    if (!saveName.trim() || (saveKind === "new" && !saveText.trim()) || dialogBusy || !storageReady || promptsBusy) return;
    setDialogBusy(true);
    setDialogError("");
    setError("");
    setNotice("");
    try {
      const source = saveKind === "new" ? { prompt: saveText, target: saveTarget } : saveSourceRef.current;
      if (
        pendingPromptRef.current?.title !== saveName.trim() ||
        pendingPromptRef.current?.prompt !== source.prompt ||
        pendingPromptRef.current?.target !== source.target
      )
        pendingPromptRef.current = {
          id: crypto.randomUUID(),
          title: saveName.trim(),
          ...source,
          createdAt: new Date().toISOString(),
        };
      const data = await api("/prompts", pendingPromptRef.current);
      setSaved(data.prompts);
      setNotice("Prompt saved to the local JSON file.");
      setSaveKind(null);
    } catch (err) {
      setDialogError(`Could not save. ${err.message}`);
    } finally {
      setDialogBusy(false);
    }
  }

  return {
    saved, storageReady, storageWarning, storageError, promptsBusy, saveKind, dialogBusy,
    reload, deletePrompt, requestPromptSave, requestNewPrompt,
    dialog: { dialogRef, saveNameRef, dialogBusy, dialogError, saveName, setSaveName,
      creating: saveKind === "new", saveText, setSaveText, saveTarget, setSaveTarget,
      onSubmit: save, onClose: () => setSaveKind(null) },
  };
}
