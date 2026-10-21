import { useEffect, useRef, useState } from "react";
import { Images, RefreshCw, Save } from "lucide-react";
import { api } from "../../api.js";
import { ui } from "../../ui.js";

const statusLabels = { saved: "Captioned", skipped: "Existing caption kept", missing: "No prompt found", error: "Error" };

function imageUrl(folder, file) {
  const query = new URLSearchParams({ folder, name: file.image, v: String(file.modified) });
  return `/api/caption/image?${query}`;
}

function CaptionCard({ folder, file, run, onSaved, regenerate }) {
  const [draft, setDraft] = useState(file.caption ?? "");
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const dirty = draft !== (file.caption ?? "");

  // A newer caption from the folder replaces the text only when there are no unsaved edits.
  const shown = useRef(file.caption ?? "");
  useEffect(() => {
    const next = file.caption ?? "";
    setDraft((current) => (current === shown.current ? next : current));
    shown.current = next;
  }, [file.caption]);

  async function save() {
    setSaving(true);
    setError("");
    setMessage("");
    try {
      const saved = await api("/caption/text", { input: { folder, image: file.image, caption: draft } }, "PUT");
      onSaved(file.image, saved.caption);
      setMessage(`Saved to ${saved.caption_file}`);
    } catch (err) { setError(err.message); }
    finally { setSaving(false); }
  }

  async function regenerateCaption() {
    setError("");
    setMessage("");
    setDraft(shown.current);  // The new caption replaces the file, so drop unsaved edits.
    try {
      const outcome = await regenerate.start(file.image);
      if (outcome?.error) setError(outcome.error);
      else if (outcome?.status === "saved") setMessage("New caption saved.");
    } catch (err) { setError(err.message); }
  }

  function onKeyDown(event) {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
      event.preventDefault();
      if (dirty && draft.trim() && !saving) save();
    }
  }

  return <li className={`${ui.panel} flex min-w-0 flex-col gap-3 p-3`}>
    <img src={imageUrl(folder, file)} alt={file.image} loading="lazy"
      className="aspect-square w-full rounded-lg bg-black/5 object-contain" />
    <div className="flex flex-wrap items-baseline justify-between gap-2 text-sm">
      <span className="break-all font-semibold">{file.image}</span>
      <span className="text-xs text-muted">{dirty ? "Unsaved changes" : file.caption === null ? "No caption yet" : run ? statusLabels[run.status] || "" : file.caption_file}</span>
    </div>
    <textarea className={ui.notesInput} rows={6} maxLength={20000} value={draft} aria-label={`Caption for ${file.image}`}
      placeholder="No caption file yet. Write one and save." onChange={(event) => { setDraft(event.target.value); setMessage(""); }}
      onKeyDown={onKeyDown} />
    {run?.error && !dirty && <p className={ui.warningNote}>{run.error}</p>}
    {error && <p className={ui.warningNote} role="alert">{error}</p>}
    <div className="flex flex-wrap items-center justify-between gap-2">
      <small className="text-xs text-muted" role="status">{message}</small>
      <div className="flex flex-wrap gap-2">
        <button type="button" className={ui.button} disabled={saving || !!regenerate.blocked || regenerate.active === file.image}
          title={regenerate.blocked || `Write a new caption for this image only (${regenerate.label}); replaces its text file.`}
          onClick={regenerateCaption}>
          <RefreshCw size={15} className={regenerate.active === file.image ? "animate-spin" : ""} />
          {regenerate.active === file.image ? "Regenerating…" : "Regenerate"}
        </button>
        {dirty && <button type="button" className={ui.button} disabled={saving} onClick={() => setDraft(file.caption ?? "")}>Undo</button>}
        <button type="button" className={ui.primaryButton} disabled={!dirty || !draft.trim() || saving} onClick={save}>
          <Save size={15} />{saving ? "Saving…" : "Save"}
        </button>
      </div>
    </div>
  </li>;
}

export default function CaptionEditor({ folder, runFiles, reloadKey, regenerate }) {
  const [listing, setListing] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [refresh, setRefresh] = useState(0);
  const runByImage = Object.fromEntries((runFiles || []).map((row) => [row.image, row]));

  useEffect(() => {
    if (!folder) { setListing(null); return undefined; }
    let current = true;
    setLoading(true);
    setError("");
    api("/caption/files", { input: { folder } })
      .then((result) => { if (current) setListing(result); })
      .catch((err) => { if (current) { setListing(null); setError(err.message); } })
      .finally(() => { if (current) setLoading(false); });
    return () => { current = false; };
  }, [folder, reloadKey, refresh]);

  function onSaved(image, caption) {
    setListing((current) => current && { ...current,
      files: current.files.map((file) => file.image === image ? { ...file, caption } : file) });
  }

  if (!folder) return null;
  const captioned = listing ? listing.files.filter((file) => file.caption !== null).length : 0;

  return <section className="mt-6" aria-label="Images and captions">
    <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
      <div className="flex items-center gap-2"><Images size={19} /><h2 className="text-lg font-semibold">Images &amp; captions</h2>
        {listing && <span className="text-sm text-muted">{captioned} of {listing.files.length} captioned</span>}</div>
      <button type="button" className={ui.button} disabled={loading} onClick={() => setRefresh((value) => value + 1)}>
        <RefreshCw size={15} />{loading ? "Loading…" : "Reload from folder"}</button>
    </div>
    <p className="mb-2 break-all text-sm text-muted">{listing?.folder || folder}</p>
    <p className={`${ui.subtleNote} mb-4`}>Edit any caption and press Save (or Ctrl+S) to overwrite its text file.</p>
    {error && <p className={ui.subtleNote} role="status">{error}</p>}
    {listing && listing.files.length === 0 && <p className={ui.subtleNote}>No PNG, JPG or WebP images in this folder.</p>}
    {listing && <ul className="grid grid-cols-[repeat(auto-fill,minmax(260px,1fr))] gap-4">
      {listing.files.map((file) => <CaptionCard key={file.image} folder={listing.folder} file={file}
        run={runByImage[file.image]} onSaved={onSaved} regenerate={regenerate} />)}
    </ul>}
  </section>;
}
