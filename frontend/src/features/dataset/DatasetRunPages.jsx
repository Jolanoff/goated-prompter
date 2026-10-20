import { ChevronDown, Copy, Database, Download, FileJson, Layers3, LoaderCircle } from "lucide-react";
import { ui } from "../../ui.js";
import { datasetCopyText } from "./datasetExport.js";

// Rebuild (issue 106): the Scenes and Dataset pages for a run started by Confirm.
const pad = (number) => String(number).padStart(2, "0");
const STAGES = { scene: "scene", composition: "composition", concepts: "concept", staging: "staging",
  description: "description", finishing: "finishing" };

const slotOf = (item, position) => (Number.isInteger(item?.slot) && item.slot > 0 ? item.slot
  : Number.isInteger(item?.index) && item.index > 0 ? item.index : position + 1);

/** One record per requested image, by its stable slot: status, guided input, scene and prompt.
 * Older results without slots fall back to list positions. */
export function runSlots(result) {
  if (!result) return [];
  const scenes = new Map((result.scenes || []).map((scene, position) => [slotOf(scene, position), scene]));
  const prompts = new Map((result.prompts || []).map((item, position) => [slotOf(item, position), item]));
  const records = result.slots?.length ? result.slots
    : [...new Set([...scenes.keys(), ...prompts.keys(), ...(result.missing || []).map((item) => item.slot)])].sort((a, b) => a - b)
      .map((slot) => ({ slot, status: scenes.has(slot) || prompts.has(slot) ? "written" : "failed", input: "",
        ...(result.missing || []).find((item) => item.slot === slot) }));
  return records.map((record) => ({ ...record, scene: scenes.get(record.slot) || null, prompt: prompts.get(record.slot) || null }));
}

/** Final prompts in slot order; failed or empty prompts are left out, never written as blank lines. */
export function writtenPrompts(result) {
  return runSlots(result).map((record) => record.prompt).filter((item) => item?.prompt?.trim());
}

function Line({ label, children }) {
  return <p className="dataset-scene-source"><strong>{label}:</strong> {children}</p>;
}

function SceneDetails({ scene }) {
  return <>
    {Object.entries(scene.position).map(([label, text]) => <Line key={`position-${label}`} label={`Position · ${label}`}>{text}</Line>)}
    <Line label="Action">{scene.actions}</Line>
    {scene.entry && <Line label="Vocabulary entry">{scene.entry}</Line>}
    {Object.entries(scene.subjects).map(([label, person]) => <Line key={`subject-${label}`} label={label}>
      {[person.skin, person.build, person.hair, person.detail, person.expression, person.clothing].filter(Boolean).join(" · ")}</Line>)}
    <Line label="Space">{scene.space}</Line>
    <Line label="Camera">{scene.camera}</Line>
    <Line label="Extras">{scene.extras}</Line>
  </>;
}

function Waiting({ icon: Icon, title, text }) {
  return <div className={`${ui.emptyState} dataset-empty`}>
    <Icon size={34} aria-hidden="true" className={Icon === LoaderCircle ? "dataset-loader" : undefined} /><h3>{title}</h3><p>{text}</p>
  </div>;
}

function RunNotes({ run }) {
  const result = run.result;
  return <>
    {run.error && <p className={`${ui.warningNote} mt-3`} role="alert">{run.error}</p>}
    {run.status !== "running" && result && !result.complete && result.written < result.requested && <p className={`${ui.warningNote} mt-3`} role="status">
      Incomplete: {result.written} of {result.requested} scenes written. Not written: {(result.missing || []).map((item) => `image ${item.slot}`).join(", ")}. Each image below says why.</p>}
    {run.status !== "running" && result?.prompt_summary?.missing.length > 0 && <p className={`${ui.warningNote} mt-3`} role="status">
      Incomplete: {result.prompt_summary.written} of {result.requested} final prompts written. Not written: {result.prompt_summary.missing.map((slot) => `image ${slot}`).join(", ")}. Per-image errors are shown below.</p>}
  </>;
}

function NotWritten({ record }) {
  return <p className={`${ui.warningNote} mt-2`}>
    Not written{record.stage ? ` (${STAGES[record.stage] || record.stage} failed)` : ""}.
    {record.reasons?.length ? ` ${record.reasons.join(" ")}` : ""}</p>;
}

export function RunScenes({ run, onCopy, onDownload }) {
  const scenes = run.result?.scenes || [];
  const records = runSlots(run.result);
  const writing = run.status === "running" && run.result?.stage === "writing_scenes";
  return <section className={`${ui.panel} dataset-scenes-panel`} aria-label="Scenes">
    <header className={ui.panelHeader}>
      <div className={ui.panelIcon}><Layers3 size={21} /></div>
      <div className={ui.panelHeading}><h2>Scenes</h2><p>One scene per image, composed from your request and any vocabulary you selected.</p></div>
    </header>
    <RunNotes run={run} />
    {!scenes.length ? (run.status === "running"
      ? <Waiting icon={LoaderCircle} title="Writing scenes…" text="Each scene appears here as soon as it is written; the final prompts start when all are done." />
      : <Waiting icon={Layers3} title="No scenes" text="This run stopped before any scene was written." />) : <>
      {writing && <p className="mt-3 flex items-center gap-2 text-xs text-muted" role="status">
        <LoaderCircle size={14} className="dataset-loader" aria-hidden="true" />
        Scenes appear as they are written: {scenes.length} of {run.result.requested}.</p>}
      <div className="mt-4 flex flex-wrap gap-3">
        <button className={ui.button} onClick={() => onCopy(JSON.stringify(scenes, null, 2))}><Copy size={14} />Copy scenes JSON</button>
        <button className={ui.button} onClick={() => onDownload("dataset-scenes.json", JSON.stringify(scenes, null, 2), "application/json")}><FileJson size={14} />Scenes JSON</button>
      </div>
      <div className="dataset-card-grid mt-4">
        {records.map((record) => <article key={record.slot} className="dataset-card dataset-scene-card" aria-label={`Image ${record.slot}`}>
          <header className="dataset-card-header dataset-scene-header">
            <div className="dataset-scene-title"><Layers3 size={18} aria-hidden="true" /><h3>Image <span>{pad(record.slot)}</span></h3></div>
            {record.scene && <button className={ui.button} onClick={() => onCopy(JSON.stringify(record.scene, null, 2))}><Copy size={14} aria-hidden="true" />Copy</button>}
          </header>
          <div className="dataset-scene-body">
            {record.input && <Line label="Input">{record.input}</Line>}
            {record.scene ? <SceneDetails scene={record.scene} /> : <NotWritten record={record} />}
          </div>
        </article>)}
      </div>
    </>}
  </section>;
}

export function RunPrompts({ run, onCopy, onDownload }) {
  const result = run.result;
  const prompts = result?.prompts || [];
  const writingScenes = result?.stage === "writing_scenes";
  const total = writingScenes ? 0 : result?.scenes?.length || 0;
  const records = runSlots(result).filter((record) => record.prompt || record.status === "failed");
  const written = writtenPrompts(result);
  const text = written.map((item) => item.prompt).join("\n\n");
  const json = JSON.stringify({ brief: run.brief, ...result }, null, 2);
  return <section aria-label="Dataset results">
    <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
      <div><h3 className="font-display text-lg font-bold">Generated dataset</h3>
        <p className="mt-1 text-xs text-muted">{run.status === "running" && total
          ? `Final prompts appear as they are written: ${prompts.length} of ${total}.` : `${written.length} final prompt${written.length === 1 ? "" : "s"}${written.length < prompts.length ? `, ${prompts.length - written.length} failed` : ""}.`}</p></div>
      <div className="flex flex-wrap gap-2">
        <button className={ui.button} disabled={!written.length} onClick={() => onCopy(datasetCopyText({ results: written }))}><Copy size={15} />Copy all</button>
        <button className={ui.button} disabled={!written.length} onClick={() => onDownload("dataset-prompts.txt", text, "text/plain;charset=utf-8")}><Download size={15} />TXT</button>
        <button className={ui.button} disabled={!result} onClick={() => onDownload("dataset.json", json, "application/json")}><FileJson size={15} />JSON</button>
      </div>
    </div>
    <RunNotes run={run} />
    {!prompts.length ? (run.status === "running"
      ? <Waiting icon={LoaderCircle} title={total ? "Writing final prompts…" : "Writing scenes…"} text="Each final prompt appears here as soon as it is written." />
      : <Waiting icon={Database} title="No prompts" text="This run stopped before any final prompt was written." />)
      : <div className="dataset-card-grid">
        {records.map(({ slot, prompt: item, scene, ...record }) => <article className="dataset-card dataset-result-card panel" key={slot} aria-label={`Image ${slot}`}>
          <div className="dataset-card-header">
            <span className="text-sm font-semibold text-accent">Image {slot}</span>
            {item?.prompt && <button className={ui.button} onClick={() => onCopy(item.prompt)}><Copy size={14} aria-hidden="true" />Copy</button>}
          </div>
          {record.input && <Line label="Input">{record.input}</Line>}
          {!item ? <NotWritten record={record} /> : <>
            {item.error ? <p className={`${ui.warningNote} mt-2`}>The final prompt failed. {item.error}</p>
              : !item.trigger_ok && <p className={`${ui.warningNote} mt-2`}>A trigger is missing or not at the start.</p>}
            <textarea className={ui.outputInput} style={{ minHeight: 220 }} aria-label={`Dataset prompt ${slot}`}
              value={item.prompt} readOnly />
          </>}
          {scene && <details className="dataset-details rounded-lg border border-line p-3 text-xs">
            <summary><Layers3 size={14} aria-hidden="true" /><span>Scene {slot}</span><ChevronDown size={14} aria-hidden="true" /></summary>
            <div className="mt-2"><SceneDetails scene={scene} /></div>
          </details>}
        </article>)}
      </div>}
  </section>;
}
