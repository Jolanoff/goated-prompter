import { useEffect, useRef, useState } from "react";
import { FileSearch, FolderOpen, ScanText } from "lucide-react";
import { api } from "../../api.js";
import { ui } from "../../ui.js";
import { targets, lengths, loraTypes, sources } from "./options.js";
import CaptionEditor from "./CaptionEditor.jsx";

export default function CaptionTab({ visible, job, busy, active, noEngine, engineLabel, onGenerate, onCancel }) {
  const [draft, setDraft] = useState({ folder: "", target: targets[0], description: "", length: "detailed", lora_type: "character", trigger: "" });
  const [source, setSource] = useState(sources[0][0]);
  const [metadataResult, setMetadataResult] = useState(null);
  const [metadataRun, setMetadataRun] = useState(0);
  const [error, setError] = useState("");
  const [choosing, setChoosing] = useState(false);
  const [starting, setStarting] = useState(false);
  const submitting = useRef(false);
  const fromMetadata = source === "metadata";
  const disabled = (!fromMetadata && busy) || choosing || starting;
  const captionJob = job?.kind === "caption" ? job : null;
  const running = active && !!captionJob;
  const result = fromMetadata ? metadataResult : captionJob?.result;
  const sourceHelp = (sources.find(([value]) => value === source) || sources[0])[2];
  const [editorFolder, setEditorFolder] = useState("");
  const [reloadKey, setReloadKey] = useState(0);
  const [regenerating, setRegenerating] = useState("");
  const update = (key, value) => setDraft((current) => ({ ...current, [key]: value }));
  const problems = result ? result.files.filter((file) => file.error) : [];

  // The folder's images and captions always show: follow the folder path (after typing pauses), and reload
  // as a run writes captions and once when it finishes. Job polling repeats snapshots, so key on changes.
  const folderPath = draft.folder.trim();
  useEffect(() => {
    const timer = setTimeout(() => setEditorFolder(folderPath), 400);
    return () => clearTimeout(timer);
  }, [folderPath]);
  const finishedRun = !result ? "" : fromMetadata ? `metadata-${metadataRun}` : `job-${captionJob?.id || ""}`;
  const liveProgress = running ? captionJob.progress || "" : "";
  useEffect(() => {
    if (finishedRun || liveProgress) setReloadKey((value) => value + 1);
  }, [finishedRun, liveProgress]);

  // While a one-image AI caption job runs, its card shows progress; the job's finish reloads the folder.
  useEffect(() => { if (!running && !fromMetadata) setRegenerating(""); }, [running, fromMetadata]);

  async function regenerateImage(image) {
    setRegenerating(image);
    try {
      if (fromMetadata) {
        const outcome = await api("/caption/metadata", { input: { folder: editorFolder, trigger: draft.trigger, image } });
        setReloadKey((value) => value + 1);
        return outcome.files[0];
      }
      const started = await onGenerate("caption", { input: { ...draft, folder: editorFolder, image } });
      if (!started) { setRegenerating(""); throw new Error("Captioning could not start. Wait for the current job to finish."); }
      return null;
    } catch (err) {
      setRegenerating("");
      throw err;
    } finally {
      if (fromMetadata) setRegenerating("");
    }
  }

  const regenerateBlocked = fromMetadata ? ""
    : noEngine ? "Choose a vision-capable engine in Builder or Settings first."
      : !draft.description.trim() ? "Fill in “What are your images about?” first; it guides the caption."
        : busy || running ? "Wait for the current job to finish." : "";
  const regenerate = { start: regenerateImage, active: regenerating, blocked: regenerateBlocked,
    label: fromMetadata ? "read from the image's metadata" : "described with AI using the settings above" };

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
    if (disabled || submitting.current) return;
    if (!fromMetadata && noEngine) return;
    submitting.current = true;
    setStarting(true);
    setError("");
    try {
      if (fromMetadata) {
        setMetadataResult(await api("/caption/metadata", { input: { folder: draft.folder, trigger: draft.trigger } }));
        setMetadataRun((value) => value + 1);
      } else {
        await onGenerate("caption", { input: draft });
      }
    } catch (err) { setError(err.message); }
    finally { submitting.current = false; setStarting(false); }
  }

  const canSubmit = draft.folder.trim() && (fromMetadata || (!noEngine && draft.description.trim()));
  const idleMessage = fromMetadata ? "Choose a folder of generated images to read their saved prompts."
    : running ? "Captioning images one by one. Results appear when the job finishes."
      : "Choose a folder and describe your dataset to start.";

  return <div hidden={!visible}>
    <div className={ui.pageHeading}><div><h2>Caption</h2><p>Turn an image folder into a captioned LoRA dataset.</p></div></div>
    {error && <div className={ui.message} role="alert">{error}</div>}
    <div className={ui.workflowStatus}>
      <span>{fromMetadata ? "Reading prompts from image metadata — no engine needed." : noEngine ? "Choose a vision-capable engine in Builder or Settings." : `Captioning engine: ${engineLabel}`}</span>
      <span role="status">{running ? captionJob.progress || "Starting captioning…" : "Images stay in their folder. Existing captions are kept."}</span>
      {running && <button className={ui.button} onClick={onCancel} disabled={job.status === "cancelling"}>Stop captioning</button>}
    </div>
    <div className="grid grid-cols-[minmax(300px,1fr)_minmax(0,1.3fr)] items-start gap-6 tablet:grid-cols-1">
      <form className={ui.panel} onSubmit={generate}>
        <header className={ui.panelHeader}><div className={ui.panelIcon}><FolderOpen size={21} /></div><div className={ui.panelHeading}><h2>Image folder</h2><p>One image, one matching text file.</p></div></header>
        <fieldset disabled={disabled} className="min-w-0 border-0 p-0">
          <fieldset className="mb-4 border-0 p-0">
            <legend className="mb-2 text-xs font-semibold">Caption source</legend>
            <div className="grid grid-cols-2 gap-2 tiny:grid-cols-1">
              {sources.map(([value, label]) => <label key={value} className={`${ui.choiceCard} block`}>
                <span className="flex items-center gap-2 text-xs font-semibold"><input type="radio" name="caption-source" value={value}
                  checked={source === value} onChange={() => { setSource(value); setError(""); }} />{label}</span>
              </label>)}
            </div>
            <small className="mt-2 block text-xs leading-relaxed text-muted">{sourceHelp}</small>
          </fieldset>
          <div className={`${ui.fields} grid-cols-2 mobile:grid-cols-1`}>
            <label className={`${ui.field} col-span-full`}><span>Folder path</span><input className={ui.input} required maxLength={4096} value={draft.folder} onChange={(event) => update("folder", event.target.value)} placeholder="Paste a folder path on this computer" /></label>
            <button className={`${ui.button} col-span-full`} type="button" onClick={chooseFolder}><FolderOpen size={16} />{choosing ? "Choosing folder…" : "Choose folder"}</button>
            {!fromMetadata && <>
              <label className={ui.field}><span>Target model</span><select className={ui.select} value={draft.target} onChange={(event) => update("target", event.target.value)}>{targets.map((target) => <option key={target}>{target}</option>)}</select></label>
              <label className={ui.field}><span>LoRA type</span><select className={ui.select} value={draft.lora_type} onChange={(event) => update("lora_type", event.target.value)}>{loraTypes.map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label>
              <label className={`${ui.field} col-span-full`}><span>What are your images about?</span><textarea className={ui.notesInput} rows={4} required maxLength={10000} value={draft.description} onChange={(event) => update("description", event.target.value)} placeholder="In your own words: who is in the images and what they are doing. Example: action LoRA, a man and a woman dancing together; each image shows a different dance move." /><small className={ui.subtleNote}>Captions reuse your words for the subjects and the concept, then describe what each image shows.</small></label>
              <label className={`${ui.field} col-span-full`}><span>Caption length</span><select className={ui.select} value={draft.length} onChange={(event) => update("length", event.target.value)}>{lengths.map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label>
            </>}
            <label className={`${ui.field} col-span-full`}><span>Trigger phrase (optional)</span><input className={ui.input} maxLength={200} value={draft.trigger} onChange={(event) => update("trigger", event.target.value)} placeholder="Your training trigger" /><small className={ui.subtleNote}>Added unchanged to the start of each new caption.</small></label>
          </div>
          {fromMetadata
            ? <p className={ui.subtleNote}>Reads the positive prompt saved in PNG, JPG and WebP files (ComfyUI graphs and workflows, or a “parameters” block). Images whose final prompt is not saved in the file are reported as failed and get no text file.</p>
            : <>
              <p className={ui.subtleNote}>Krea 2 captions use plain, neutral natural language. Style captions describe content without explaining the style. Action captions name the visible variant of the action or pose.</p>
              <p className={ui.subtleNote}>PNG, JPG, JPEG and WebP, up to 20 MiB each. Only this folder, not subfolders. Images are sent to your configured engine; a remote engine receives their contents.</p>
            </>}
          <button className={`${ui.primaryButton} mt-5`} type="submit" disabled={!canSubmit}>
            {fromMetadata ? <FileSearch size={17} /> : <ScanText size={17} />}
            {starting ? (fromMetadata ? "Reading…" : "Starting…") : fromMetadata ? "Extract prompts" : "Caption folder"}
          </button>
        </fieldset>
      </form>
      <section className={`${ui.panel} min-w-0`} aria-label="Caption results">
        <header className={ui.panelHeader}><div className={ui.panelIcon}><ScanText size={21} /></div><div className={ui.panelHeading}><h2>Caption files</h2><p>image.png → image.txt</p></div></header>
        <p className={ui.subtleNote}>Each finished caption is saved beside its image. {fromMetadata ? "Delete a text file and run again to re-extract it." : "Stopping keeps completed files; run again to caption the remaining images."} Review captions before training.</p>
        {!fromMetadata && captionJob?.error && <p className={ui.warningNote} role="alert">{captionJob.error}</p>}
        {!fromMetadata && captionJob?.status === "cancelled" && <p role="status">Captioning stopped. Completed text files remain in the folder.</p>}
        {result ? <>
          <p role="status">{result.saved} saved · {result.skipped} existing{result.missing !== undefined ? ` · ${result.missing} without a prompt` : ""} · {result.errors} errors</p>
          <p className="my-3 break-all text-sm text-muted">{result.folder}</p>
          <p className="text-sm text-muted">Every image and its caption is shown below, where you can edit and save it.</p>
          {problems.length > 0 && <ul className="mt-3 max-h-[40vh] space-y-3 overflow-y-auto" aria-label="Images that need attention">{problems.map((file) => <li key={file.image} className="border-t border-line pt-3 text-sm">
            <span className="break-all font-semibold">{file.image}</span>
            <p className={ui.warningNote}>{file.error}</p>
          </li>)}</ul>}
        </> : <p className="mt-5 text-sm text-muted">{idleMessage}</p>}
      </section>
    </div>
    <CaptionEditor folder={editorFolder} runFiles={result?.files} reloadKey={reloadKey} regenerate={regenerate} />
  </div>;
}
