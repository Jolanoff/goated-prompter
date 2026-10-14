import { ChevronDown, Copy, Database, Download, FileJson, Layers3, LoaderCircle } from "lucide-react";
import { ui } from "../../ui.js";

// Rebuild (issue 106): the Scenes and Dataset pages for a run started by Confirm.
const pad = (number) => String(number).padStart(2, "0");

function Line({ label, children }) {
  return <p className="dataset-scene-source"><strong>{label}:</strong> {children}</p>;
}

function SceneDetails({ scene }) {
  return <>
    {Object.entries(scene.position).map(([label, text]) => <Line key={`position-${label}`} label={`Position · ${label}`}>{text}</Line>)}
    <Line label="Action">{scene.actions}</Line>
    {Object.entries(scene.subjects).map(([label, person]) => <Line key={`subject-${label}`} label={label}>
      {[person.skin, person.build, person.hair, person.detail, person.clothing].join(" · ")}</Line>)}
    <Line label="Space">{scene.space}</Line>
    <Line label="Lighting">{scene.lighting}</Line>
    <Line label="Mood">{scene.mood}</Line>
    <Line label="Camera">{scene.camera}</Line>
    <Line label="Extras">{scene.extras}</Line>
  </>;
}

function Waiting({ icon: Icon, title, text }) {
  return <div className={`${ui.emptyState} dataset-empty`}>
    <Icon size={34} aria-hidden="true" /><h3>{title}</h3><p>{text}</p>
  </div>;
}

function RunNotes({ run }) {
  const result = run.result;
  return <>
    {run.error && <p className={`${ui.warningNote} mt-3`} role="alert">{run.error}</p>}
    {result && !result.complete && <p className={`${ui.warningNote} mt-3`} role="status">
      Incomplete: {result.written} of {result.requested} scenes written. Not written: {result.missing.map((item) => `concept ${item.slot}`).join(", ")}. The debug file says why.</p>}
  </>;
}

export function RunScenes({ run, onCopy, onDownload }) {
  const scenes = run.result?.scenes || [];
  return <section className={`${ui.panel} dataset-scenes-panel`} aria-label="Scenes">
    <header className={ui.panelHeader}>
      <div className={ui.panelIcon}><Layers3 size={21} /></div>
      <div className={ui.panelHeading}><h2>Scenes</h2><p>One scene per image: the bodies first, then everything around them.</p></div>
    </header>
    <RunNotes run={run} />
    {!scenes.length ? (run.status === "running"
      ? <Waiting icon={LoaderCircle} title="Writing scenes…" text="Scenes appear here when they are all written, then the final prompts start." />
      : <Waiting icon={Layers3} title="No scenes" text="This run stopped before any scene was written." />) : <>
      <div className="mt-4 flex flex-wrap gap-3">
        <button className={ui.button} onClick={() => onCopy(JSON.stringify(scenes, null, 2))}><Copy size={14} />Copy scenes JSON</button>
        <button className={ui.button} onClick={() => onDownload("dataset-scenes.json", JSON.stringify(scenes, null, 2), "application/json")}><FileJson size={14} />Scenes JSON</button>
      </div>
      <div className="dataset-card-grid mt-4">
        {scenes.map((scene, index) => <article key={index} className="dataset-card dataset-scene-card" aria-label={`Scene ${index + 1}`}>
          <header className="dataset-card-header dataset-scene-header">
            <div className="dataset-scene-title"><Layers3 size={18} aria-hidden="true" /><h3>Scene <span>{pad(index + 1)}</span></h3></div>
            <button className={ui.button} onClick={() => onCopy(JSON.stringify(scene, null, 2))}><Copy size={14} aria-hidden="true" />Copy</button>
          </header>
          <div className="dataset-scene-body"><SceneDetails scene={scene} /></div>
        </article>)}
      </div>
    </>}
  </section>;
}

export function RunPrompts({ run, onCopy, onDownload }) {
  const result = run.result;
  const prompts = result?.prompts || [];
  const total = result?.scenes?.length || 0;
  const text = prompts.map((item) => item.prompt).join("\n\n");
  const json = JSON.stringify({ brief: run.brief, ...result }, null, 2);
  return <section aria-label="Dataset results">
    <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
      <div><h3 className="font-display text-lg font-bold">Generated dataset</h3>
        <p className="mt-1 text-xs text-muted">{run.status === "running" && total
          ? `Final prompts appear as they are written: ${prompts.length} of ${total}.` : `${prompts.length} final prompts.`}</p></div>
      <div className="flex flex-wrap gap-2">
        <button className={ui.button} disabled={!prompts.length} onClick={() => onCopy(text)}><Copy size={15} />Copy all</button>
        <button className={ui.button} disabled={!prompts.length} onClick={() => onDownload("dataset-prompts.txt", text, "text/plain;charset=utf-8")}><Download size={15} />TXT</button>
        <button className={ui.button} disabled={!result} onClick={() => onDownload("dataset.json", json, "application/json")}><FileJson size={15} />JSON</button>
      </div>
    </div>
    <RunNotes run={run} />
    {!prompts.length ? (run.status === "running"
      ? <Waiting icon={LoaderCircle} title={total ? "Writing final prompts…" : "Writing scenes…"} text="Each final prompt appears here as soon as it is written." />
      : <Waiting icon={Database} title="No prompts" text="This run stopped before any final prompt was written." />)
      : <div className="dataset-card-grid">
        {prompts.map((item) => {
          const scene = result.scenes[item.index - 1];
          return <article className="dataset-card dataset-result-card panel" key={item.index}>
            <div className="dataset-card-header">
              <span className="text-sm font-semibold text-accent">Prompt {item.index}</span>
              <button className={ui.button} onClick={() => onCopy(item.prompt)}><Copy size={14} aria-hidden="true" />Copy</button>
            </div>
            {!item.trigger_ok && <p className={`${ui.warningNote} mt-2`}>The trigger is missing or not at the start.</p>}
            <textarea className={ui.outputInput} style={{ minHeight: 220 }} aria-label={`Dataset prompt ${item.index}`}
              value={item.prompt} readOnly />
            {scene && <details className="dataset-details rounded-lg border border-line p-3 text-xs">
              <summary><Layers3 size={14} aria-hidden="true" /><span>Scene {item.index}</span><ChevronDown size={14} aria-hidden="true" /></summary>
              <div className="mt-2"><SceneDetails scene={scene} /></div>
            </details>}
          </article>;
        })}
      </div>}
  </section>;
}
