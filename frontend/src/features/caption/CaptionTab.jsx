import { useRef, useState } from "react";
import { FolderOpen, ScanText } from "lucide-react";
import { api } from "../../api.js";
import { ui } from "../../ui.js";
import { targets, lengths, loraTypes } from "./options.js";

export default function CaptionTab({ visible, job, busy, active, noEngine, engineLabel, onGenerate, onCancel }) {
  const [draft, setDraft] = useState({ folder: "", target: targets[0], description: "", length: "detailed", lora_type: "character", trigger: "" });
  const [error, setError] = useState("");
  const [choosing, setChoosing] = useState(false);
  const [starting, setStarting] = useState(false);
  const submitting = useRef(false);
  const disabled = busy || choosing || starting;
  const captionJob = job?.kind === "caption" ? job : null;
  const running = active && !!captionJob;
  const result = captionJob?.result;
  const update = (key, value) => setDraft((current) => ({ ...current, [key]: value }));

  async function chooseFolder() {
    setChoosing(true);
    setError("");
    try {
      const response = await api("/caption/folder", {});
      if (response.folder) update("folder", response.folder);
    } catch (err) { setError(err.message); }
    finally { setChoosing(false); }
  }

  async function generate(event) {
    event.preventDefault();
    if (disabled || noEngine || submitting.current) return;
    submitting.current = true;
    setStarting(true);
    setError("");
    try { await onGenerate("caption", { input: draft }); }
    catch (err) { setError(err.message); }
    finally { submitting.current = false; setStarting(false); }
  }

  return <div hidden={!visible}>
    <div className={ui.pageHeading}><div><h2>Caption</h2><p>Turn an image folder into a captioned LoRA dataset.</p></div></div>
    {error && <div className={ui.message} role="alert">{error}</div>}
    <div className={ui.workflowStatus}>
      <span>{noEngine ? "Choose a vision-capable engine in Builder or Settings." : `Captioning engine: ${engineLabel}`}</span>
      <span role="status">{running ? captionJob.progress || "Starting captioning…" : "Images stay in their folder. Existing captions are kept."}</span>
      {running && <button className={ui.button} onClick={onCancel} disabled={job.status === "cancelling"}>Stop captioning</button>}
    </div>
    <div className="grid grid-cols-[minmax(300px,1fr)_minmax(0,1.3fr)] items-start gap-6 tablet:grid-cols-1">
      <form className={ui.panel} onSubmit={generate}>
        <header className={ui.panelHeader}><div className={ui.panelIcon}><FolderOpen size={21} /></div><div className={ui.panelHeading}><h2>Image folder</h2><p>One image, one matching text file.</p></div></header>
        <fieldset disabled={disabled} className="min-w-0 border-0 p-0">
          <div className={`${ui.fields} grid-cols-2 mobile:grid-cols-1`}>
            <label className={`${ui.field} col-span-full`}><span>Folder path</span><input className={ui.input} required maxLength={4096} value={draft.folder} onChange={(event) => update("folder", event.target.value)} placeholder="Paste a folder path on this computer" /></label>
            <button className={`${ui.button} col-span-full`} type="button" onClick={chooseFolder}><FolderOpen size={16} />{choosing ? "Choosing folder…" : "Choose folder"}</button>
            <label className={ui.field}><span>Target model</span><select className={ui.select} value={draft.target} onChange={(event) => update("target", event.target.value)}>{targets.map((target) => <option key={target}>{target}</option>)}</select></label>
            <label className={ui.field}><span>LoRA type</span><select className={ui.select} value={draft.lora_type} onChange={(event) => update("lora_type", event.target.value)}>{loraTypes.map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label>
            <label className={`${ui.field} col-span-full`}><span>What are your images about?</span><textarea className={ui.notesInput} rows={4} required maxLength={10000} value={draft.description} onChange={(event) => update("description", event.target.value)} placeholder="Describe the character, style, or action you want to train." /></label>
            <label className={`${ui.field} col-span-full`}><span>Caption length</span><select className={ui.select} value={draft.length} onChange={(event) => update("length", event.target.value)}>{lengths.map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label>
            <label className={`${ui.field} col-span-full`}><span>Trigger phrase (optional)</span><input className={ui.input} maxLength={200} value={draft.trigger} onChange={(event) => update("trigger", event.target.value)} placeholder="Your training trigger" /><small className={ui.subtleNote}>Added unchanged to the start of each new caption.</small></label>
          </div>
          <p className={ui.subtleNote}>Krea 2 captions use plain, neutral natural language. Style captions describe content without explaining the style. Action captions describe only the visible pose or action.</p>
          <p className={ui.subtleNote}>PNG, JPG, JPEG and WebP, up to 20 MiB each. Only this folder, not subfolders. Images are sent to your configured engine; a remote engine receives their contents.</p>
          <button className={`${ui.primaryButton} mt-5`} type="submit" disabled={noEngine || !draft.folder.trim() || !draft.description.trim()}><ScanText size={17} />{starting ? "Starting…" : "Caption folder"}</button>
        </fieldset>
      </form>
      <section className={`${ui.panel} min-w-0`} aria-label="Caption results">
        <header className={ui.panelHeader}><div className={ui.panelIcon}><ScanText size={21} /></div><div className={ui.panelHeading}><h2>Caption files</h2><p>image.png → image.txt</p></div></header>
        <p className={ui.subtleNote}>Each finished caption is saved beside its image. Stopping keeps completed files; run again to caption the remaining images. Review captions before training.</p>
        {captionJob?.error && <p className={ui.warningNote} role="alert">{captionJob.error}</p>}
        {captionJob?.status === "cancelled" && <p role="status">Captioning stopped. Completed text files remain in the folder.</p>}
        {result ? <>
          <p role="status">{result.saved} saved · {result.skipped} existing · {result.errors} errors</p>
          <p className="my-3 break-all text-sm text-muted">{result.folder}</p>
          <ul className="max-h-[65vh] space-y-4 overflow-y-auto" aria-label="Image captions">{result.files.map((file) => <li key={file.image} className="border-t border-line pt-3">
            <div className="flex flex-wrap justify-between gap-2 text-sm"><span className="break-all">{file.image} → {file.caption_file}</span><span>{file.status === "skipped" ? "Existing caption kept" : file.status === "saved" ? "Saved" : "Error"}</span></div>
            {file.caption && <p className="mt-2 whitespace-pre-wrap break-words text-sm text-muted">{file.caption}</p>}
            {file.error && <p className={ui.warningNote}>{file.error}</p>}
          </li>)}</ul>
        </> : <p className="mt-5 text-sm text-muted">{running ? "Captioning images one by one. Results appear when the job finishes." : "Choose a folder and describe your dataset to start."}</p>}
      </section>
    </div>
  </div>;
}
