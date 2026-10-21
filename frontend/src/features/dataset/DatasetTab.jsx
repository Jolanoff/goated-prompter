import { useEffect, useRef, useState } from "react";
import { AlignLeft, ChevronDown, CircleHelp, Cpu, Database, Download, Layers3, LoaderCircle, SlidersHorizontal, Sparkles, WandSparkles } from "lucide-react";
import { ui } from "../../ui.js";
import { orderDisplayPresets, presetDisplayLabel } from "../../presetPresentation.js";
import { TargetSelect } from "../../shared/workflow/WorkflowControls.jsx";
import { useWorkflowSettings } from "../../shared/workflow/useWorkflowSettings.js";
import WorkflowSettingsStatus from "../../shared/workflow/WorkflowSettingsStatus.jsx";
import { datasetGenerationLog } from "./datasetExport.js";
import { useDatasetWorkflow } from "./useDatasetWorkflow.js";
import DatasetConfirmationModal from "./DatasetConfirmationModal.jsx";
import DatasetVocabulary from "./DatasetVocabulary.jsx";
import DatasetTriggers from "./DatasetTriggers.jsx";
import { useCatalog } from "../vocabulary/useCatalog.js";
import { cleanSelection, recordedNames, selectedNames } from "../vocabulary/catalog.js";
import { RunPrompts, RunScenes } from "./DatasetRunPages.jsx";
import { excludedDirectors, maxSeed, seedModes } from "./options.js";
import { captures, styleChoices, styleFamily, styles, subStyleChoices } from "../../shared/workflow/options.js";

const datasetPages = [["configure", "Configure"], ["scenes", "Scenes"], ["dataset", "Dataset"]];
const sceneSources = [
  ["random", "Invent scenes", "Let Scene Planner invent scenes", "Distinct situations from your concept and the vocabulary you select."],
  ["guided", "Use my scene ideas", "Provide my own scene ideas", "One idea per line; the action stays fixed. Vocabulary is not used."],
];

function HelpDetails({ children }) {
  return <details className="dataset-help dataset-details">
    <summary><CircleHelp size={14} aria-hidden="true" />Learn more<ChevronDown size={14} aria-hidden="true" /></summary>
    <p className="mt-2 text-xs leading-relaxed text-muted">{children}</p>
  </details>;
}

function elapsedLabel(seconds) {
  const minutes = Math.floor(seconds / 60);
  const remainder = seconds % 60;
  return minutes ? `${minutes}m ${remainder}s` : `${remainder}s`;
}

function download(name, content, type) {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

export default function DatasetTab({ visible, job, busy, active, noEngine, engineLabel, presets,
  targets, lengths, onGenerate, onCancel, onCopy }) {
  const preferences = useWorkflowSettings("dataset");
  const { draft, update } = preferences;
  const [page, setPage] = useState("configure");
  const availablePresets = orderDisplayPresets((presets || []).filter((item) => !excludedDirectors.includes(item.id)));
  const director = availablePresets.find((item) => item.id === draft?.director_preset);
  const vocabulary = useCatalog(visible);
  const selectedPacks = cleanSelection(vocabulary.catalog, draft?.vocabulary_packs);
  const { error, workflowActive, disabled, guidedLines, canPlanScenes, canWrite, generateDataset, generateScenes,
    confirmation, understanding, run, cancelConfirmation, confirmRequest } = useDatasetWorkflow({ preferences, job, busy, active, noEngine,
      director, onGenerate });
  // A run shows the vocabulary it was confirmed with, never the library's current choice.
  const runPacks = run && (run.result?.vocabulary?.selection ? recordedNames(run.result.vocabulary.selection)
    : selectedNames(vocabulary.catalog, run.vocabulary));
  const recordedPacks = run && <section className="pack-picker-record" aria-label="Vocabulary for this run">
    <h3>Vocabulary for this run</h3>
    <p>{runPacks.length ? runPacks.join(", ") : "No packs selected"}</p>
  </section>;
  const [clock, setClock] = useState(Date.now());

  const stageSeconds = workflowActive
    ? Math.max(0, Math.floor(clock / 1000 - (job.progress_at || job.created_at || clock / 1000)))
    : 0;

  useEffect(() => {
    if (!workflowActive) return;
    setClock(Date.now());
    const timer = setInterval(() => setClock(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [workflowActive, job?.id, job?.progress_at]);

  const runActive = active && job?.kind === "dataset_v2_scenes";
  const generationUnit = `prompt${draft?.amount === 1 ? "" : "s"}`;

  // Rebuild (issue 106): after Confirm, show Scenes while scenes are written, then Dataset once prompts arrive.
  const shownRun = useRef("");
  const advancedRun = useRef("");
  useEffect(() => {
    if (!run) return;
    if (shownRun.current !== run.jobId) {
      shownRun.current = run.jobId;
      setPage("scenes");
      window.scrollTo({ top: 0 });
    }
    if (advancedRun.current !== run.jobId && run.result?.prompts?.length) {
      advancedRun.current = run.jobId;
      setPage("dataset");
      window.scrollTo({ top: 0 });
    }
  }, [run]);

  function exportGenerationLog() {
    download("dataset-generation-log.json", datasetGenerationLog({ draft, review: understanding, job, record: preferences.record, run,
      state: { active: workflowActive, error, settings_status: preferences.status, settings_error: preferences.error,
        settings_conflict: preferences.conflict } }), "application/json;charset=utf-8");
  }

  function goToStep(step) {
    setPage(step);
    window.scrollTo({ top: 0 });
  }

  function navigateTabs(event, index) {
    const nextIndex = event.key === "ArrowRight" ? (index + 1) % datasetPages.length
      : event.key === "ArrowLeft" ? (index + datasetPages.length - 1) % datasetPages.length
        : event.key === "Home" ? 0 : event.key === "End" ? datasetPages.length - 1 : null;
    if (nextIndex === null) return;
    event.preventDefault();
    const nextPage = datasetPages[nextIndex][0];
    goToStep(nextPage);
    document.getElementById(`dataset-tab-${nextPage}`)?.focus();
  }

  return <div className="dataset-view" hidden={!visible}>
    <div className={`${ui.pageHeading} dataset-heading`}><div>
      <h2>Build a prompt dataset</h2>
      <p>Configure your idea, review the scenes, and build your training set.</p>
    </div><button className={ui.button} onClick={exportGenerationLog} title="Download current state only. No log is saved automatically.">
      <Download size={15} aria-hidden="true" />Export generation log</button></div>
    <nav className="dataset-workflow" aria-label="Dataset workflow">
      <ol role="tablist" aria-label="Dataset pages">{datasetPages.map(([step, label], index) =>
        <li key={step} role="presentation"><button type="button" role="tab" id={`dataset-tab-${step}`}
          aria-selected={page === step} aria-controls={`dataset-${step}`} tabIndex={page === step ? 0 : -1}
          disabled={!draft} onKeyDown={(event) => navigateTabs(event, index)}
          onClick={() => goToStep(step)}><span className="dataset-step-number" aria-hidden="true">{index + 1}</span>
          <span>{label}</span></button></li>)}</ol>
    </nav>
    {error && <div className={ui.message} role="alert"><span>{error}</span></div>}
    <div className="dataset-session">
    <WorkflowSettingsStatus settings={preferences} label="Dataset" className="" />
    <div className={ui.workflowStatus}>
      <span>{noEngine ? "Choose a prompt engine in Builder or Settings to generate." : `Engine: ${engineLabel}`}</span>
      <span role="status" className="flex items-center gap-2">{workflowActive && <LoaderCircle size={15} className="dataset-loader" aria-hidden="true" />}{workflowActive ? job.status === "cancelling" ? "Ending batch…" : <>{job.progress || "Starting dataset generation…"}{stageSeconds >= 5 && ` · ${elapsedLabel(stageSeconds)}`}</> : run ? `${run.result?.prompts?.length || 0} prompts in the current batch` : "No batch yet"}</span>
      {active && <button className={ui.button} onClick={onCancel} disabled={job.status === "cancelling"}>End generation</button>}
    </div>
    </div>
    {workflowActive && stageSeconds >= 45 && <p className={`${ui.subtleNote} mb-5`} role="status">
      The current model request is still running.{" "}
      A local model may still be loading or generating. If the engine stops responding, its configured timeout will produce an error here; you can end generation now without waiting.
    </p>}

    {draft && <>
      <div id="dataset-configure" role="tabpanel" aria-labelledby="dataset-tab-configure" tabIndex={0} hidden={page !== "configure"}>
      {page === "configure" && <section className="dataset-configuration" aria-label="Configure dataset">
      <div className="dataset-config-grid">
        <section className="dataset-config-column" aria-label="Dataset trigger and concept settings">
          <header className="dataset-config-heading">
            <h3>Dataset configuration</h3><p>The subject, concept, and rules for your batch.</p>
          </header>
          <fieldset disabled={disabled} className="dataset-config-fields">
            <label className={ui.field}><span>Request</span>
              <textarea className={ui.ideaInput} aria-label="Request" maxLength={10000}
                value={draft.subject} onChange={(event) => update({ subject: event.target.value })}
                placeholder="A woman doing funny stuff · a dog going on small adventures · a knight doing office work" />
            </label>
            <label className={ui.choiceCard}>
              <input type="checkbox" className="mt-0.5" aria-label="NSFW"
                checked={draft.nsfw === true} onChange={(event) => update({ nsfw: event.target.checked })} />
              <span><strong className="block">NSFW</strong>
                <small className="mt-1 block leading-relaxed text-muted">On: adult characters and NSFW packs. Off: safe-for-work images.</small></span>
            </label>
            <div className="dataset-subject-fields">
              <label className={ui.field}><span>Amount</span>
                <select className={ui.select} aria-label="Number of prompts" value={draft.amount}
                  onChange={(event) => update({ amount: Number(event.target.value) })}>
                  {Array.from({ length: 25 }, (_, index) => index + 1).map((amount) =>
                    <option key={amount} value={amount}>{amount}</option>)}
                </select>
              </label>
            </div>
             <DatasetTriggers triggers={draft.triggers} onChange={(triggers) => update({ triggers })} />
             <details className="dataset-details dataset-advanced">
               <summary><SlidersHorizontal size={14} aria-hidden="true" /><span>Advanced options</span>
                 {draft.constraints.trim() && <span className="dataset-rules-indicator">Rules added</span>}<ChevronDown size={14} aria-hidden="true" /></summary>
               <div className="dataset-config-fields mt-4">
                 <label className={ui.field}><span>Consistency rules (optional)</span>
                   <textarea className={ui.notesInput} aria-label="Consistency rules" maxLength={10000}
                     value={draft.constraints} onChange={(event) => update({ constraints: event.target.value })}
                     placeholder={"Same hairstyle and outfit\nNo outdoor scenes\nEach image shows a different mishap"} />
                   <small className={ui.directorDescription}>One rule per line.</small>
                 </label>
                 <div className="dataset-subject-fields">
                   <label className={ui.field}><span>Seed</span>
                     <input className={ui.input} aria-label="Seed" type="number" min={0} max={maxSeed} step={1} value={draft.seed}
                       onChange={(event) => {
                         const seed = Math.trunc(Number(event.target.value));
                         if (Number.isFinite(seed)) update({ seed: Math.min(maxSeed, Math.max(0, seed)) });
                       }} />
                   </label>
                   <label className={ui.field}><span>Seed control</span>
                     <select className={ui.select} aria-label="Seed control" value={draft.seed_mode}
                       onChange={(event) => update({ seed_mode: event.target.value })}>
                       {seedModes.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                     </select>
                   </label>
                 </div>
                 <small className={ui.directorDescription}>Shows the seed of the last batch. Each new batch keeps it (Fixed), adds one (Increment) or picks a new one (Randomize). Regenerating one image stays random.</small>
                    <HelpDetails>Generate starts a fresh batch: confirm the request once, then scenes and prompts are written in order. Generate scenes only stops after the scenes. Changed settings need a new review.</HelpDetails>
               </div>
             </details>
          </fieldset>
        </section>

        <section className="dataset-config-column" aria-label="Dataset generation settings">
          <header className="dataset-config-heading">
            <h3>Model &amp; output settings</h3><p>Choose the Director, target model, prompt format and vocabulary.</p>
          </header>
          <fieldset disabled={disabled}>
            <label className={ui.field}><span><SlidersHorizontal size={14} aria-hidden="true" />Director preset</span>
              <select className={ui.select} aria-label="Dataset director preset" value={draft.director_preset} onChange={(event) => update({ director_preset: event.target.value })}>
                {!director && <option value={draft.director_preset}>Unavailable — choose a preset</option>}
                {availablePresets.map((item) => <option key={item.id} value={item.id}>{presetDisplayLabel(item)}</option>)}
              </select>
              <small className="text-xs leading-relaxed text-muted">Styles the final prompts together with the target model; the scenes themselves stay as written.</small>
            </label>
            <div className="mt-4 grid grid-cols-2 gap-4 tiny:grid-cols-1">
              <TargetSelect label="Target model" ariaLabel="Dataset target model" icon={<Cpu size={14} aria-hidden="true" />} value={draft.target} targets={targets} disabled={disabled} onChange={(target) => update({ target })} />
              <label className={ui.field}><span><AlignLeft size={14} aria-hidden="true" />Prompt length</span>
                <select className={ui.select} aria-label="Dataset prompt length" value={draft.length} onChange={(event) => update({ length: event.target.value })}>
                  {lengths.map((item) => <option key={item}>{item}</option>)}
                </select>
              </label>
            </div>

            <div className="mt-4 grid grid-cols-2 gap-4 tiny:grid-cols-1">
              <label className={ui.field}><span><Sparkles size={14} aria-hidden="true" />Creativity</span>
                <select className={ui.select} aria-label="Dataset descriptive creativity" value={draft.creativity || "Balanced"} onChange={(event) => update({ creativity: event.target.value })}>
                  {["Strict", "Balanced", "Creative", "Dice"].map((item) => <option key={item}>{item}</option>)}
                </select>
                <small className="text-xs leading-relaxed text-muted">How freely your request is interpreted; who appears and what they do never change.</small>
              </label>
              <label className={ui.field}><span><WandSparkles size={14} aria-hidden="true" />Style</span>
                <select className={ui.select} aria-label="Dataset visual style" value={styleFamily(draft.style)} onChange={(event) => update({ style: event.target.value })}>
                  {styleChoices(styles, draft.target, draft.style || "Auto").map(({ value }) => <option key={value}>{value}</option>)}
                </select>
                <small className="text-xs leading-relaxed text-muted">Auto follows your concept; with Anima it means anime.</small>
              </label>
              {subStyleChoices(styles, draft.style).length > 0 && <label className={ui.field}><span><WandSparkles size={14} aria-hidden="true" />Sub-style</span>
                <select className={ui.select} aria-label="Dataset sub-style" value={draft.style} onChange={(event) => update({ style: event.target.value })}>
                  {subStyleChoices(styles, draft.style).map(({ value, label }) => <option key={value} value={value}>{label}</option>)}
                </select>
              </label>}
              {draft.style === "Realistic" && draft.target !== "Anima" && <label className={ui.field}><span><WandSparkles size={14} aria-hidden="true" />Capture</span>
                <select className={ui.select} aria-label="Dataset photo capture" value={draft.capture || "Auto"} onChange={(event) => update({ capture: event.target.value })}>
                  {captures.map((item) => <option key={item}>{item}</option>)}
                </select>
                <small className="text-xs leading-relaxed text-muted">How the photos were taken. Auto picks one per image.</small>
              </label>}
            </div>

            <fieldset className="mt-5 border-t border-line pt-4">
              <legend className="pr-2 text-xs font-semibold">Scene source</legend>
              <div className="mt-2 grid grid-cols-3 gap-2 tiny:grid-cols-1">
                {sceneSources.map(([value, label, accessibleLabel]) =>
                   <label key={value} className={`${ui.choiceCard} block`}>
                     <span className="flex items-center gap-2 text-xs font-semibold"><input type="radio" name="dataset-source" value={value} aria-label={`${label}: ${accessibleLabel}`}
                       checked={draft.source_mode === value} onChange={() => update({ source_mode: value })} />{label}</span>
                  </label>)}
              </div>
              <small className="mt-2 block text-xs leading-relaxed text-muted">{(sceneSources.find(([value]) => value === draft.source_mode) || sceneSources[0])[3]}</small>
              {draft.source_mode === "guided" && <label className={`${ui.field} mt-4`}><span>Guided inputs · one per line ({guidedLines})</span>
                <textarea className={ui.ideaInput} aria-label="Guided dataset inputs" maxLength={50000}
                  value={draft.inputs} onChange={(event) => update({ inputs: event.target.value })}
                  placeholder={"standing portrait in a city at night\nrunning through a sunlit field\nclose-up profile in a quiet studio"} />
                   <small className={ui.directorDescription}>Lines cycle to fill the batch; each action stays fixed.</small>
              </label>}
            </fieldset>

            <div className="mt-5 border-t border-line pt-4">
              <DatasetVocabulary catalog={vocabulary.catalog} selected={selectedPacks} guided={draft.source_mode === "guided"}
                onChange={(ids) => update({ vocabulary_packs: ids })} disabled={disabled} error={vocabulary.error} />
            </div>

          </fieldset>
        </section>
      </div>
        <footer className="dataset-config-actions">
          <button className={ui.button} disabled={!canPlanScenes} onClick={generateScenes}>
            <Layers3 size={15} />Generate {draft.amount} {draft.amount === 1 ? "scene" : "scenes"} only
          </button>
          <div>
            <button className={ui.primaryButton} disabled={!canWrite} onClick={generateDataset}>
              <Sparkles size={17} />{runActive ? "Generating" : "Generate"} {draft.amount} {generationUnit}{runActive ? "…" : ""}
            </button>
          </div>
        </footer>
      </section>}
      </div>

      <div id="dataset-scenes" role="tabpanel" aria-labelledby="dataset-tab-scenes" tabIndex={0} hidden={page !== "scenes"}>
      {page === "scenes" && run && <>{recordedPacks}<RunScenes run={run} onCopy={onCopy} onDownload={download} /></>}
      {page === "scenes" && !run && <section className={`${ui.panel} dataset-scenes-panel`} aria-label="Scenes">
        <div className={`${ui.emptyState} dataset-empty`}>
          <Layers3 size={34} aria-hidden="true" /><h3>{workflowActive ? "Preparing scenes…" : "No scenes yet"}</h3>
          <p>{workflowActive ? "Scenes will appear here once the request is confirmed." : "Set up your idea on Configure, then choose Generate."}</p>
          <button className={ui.button} onClick={() => goToStep("configure")}>Back to Configure</button>
        </div>
      </section>}
      </div>

      <div id="dataset-dataset" role="tabpanel" aria-labelledby="dataset-tab-dataset" tabIndex={0} hidden={page !== "dataset"}>
      {page === "dataset" && run && <>{recordedPacks}<RunPrompts run={run} onCopy={onCopy} onDownload={download} /></>}
      {page === "dataset" && !run && <section aria-label="Dataset results">
        <div className={`${ui.emptyState} dataset-empty`}>
          <Database size={34} aria-hidden="true" /><h3>No prompts yet</h3>
          <p>Generate prompts from Configure. Completed prompts appear here as the batch runs.</p>
          <button className={ui.button} onClick={() => goToStep("configure")}>Back to Configure</button>
        </div>
      </section>}
      </div>
    </>}
    {confirmation && <DatasetConfirmationModal review={confirmation} busy={busy} catalog={vocabulary.catalog}
      directorLabel={director ? presetDisplayLabel(director) : ""}
      onConfirm={confirmRequest} onCancel={cancelConfirmation} onExport={exportGenerationLog} />}
  </div>;
}
