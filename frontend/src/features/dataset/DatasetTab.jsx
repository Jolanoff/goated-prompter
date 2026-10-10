import { useEffect, useRef, useState } from "react";
import { AlignLeft, ArrowRight, ChevronDown, Circle, CircleAlert, CircleCheck, CircleHelp, Copy, Cpu, Database, Download, FileJson, Layers3, Lightbulb, LoaderCircle, RefreshCw, SlidersHorizontal, Sparkles, Tag, Trash2, WandSparkles } from "lucide-react";
import { ui } from "../../ui.js";
import { orderDisplayPresets, presetDisplayLabel } from "../../presetPresentation.js";
import { TargetSelect } from "../../shared/workflow/WorkflowControls.jsx";
import { useWorkflowSettings } from "../../shared/workflow/useWorkflowSettings.js";
import WorkflowSettingsStatus from "../../shared/workflow/WorkflowSettingsStatus.jsx";
import LibraryStatus from "../../shared/workflow/LibraryStatus.jsx";
import { datasetCopyText, datasetJsonl, datasetGenerationLog } from "./datasetExport.js";
import { editDatasetPlan } from "./datasetState.js";
import { useDatasetWorkflow } from "./useDatasetWorkflow.js";
import DatasetConfirmationModal from "./DatasetConfirmationModal.jsx";
import { triggerTypes } from "./options.js";
import { styles } from "../../shared/workflow/options.js";

const datasetPages = [["configure", "Configure"], ["scenes", "Scenes"], ["dataset", "Dataset"]];
const sceneSources = [
  ["random", "Invent scenes", "Let Scene Planner invent scenes", "Distinct situations from your concept."],
  ["guided", "Use my scene ideas", "Provide my own scene ideas", "One idea per line; the action stays fixed."],
  ["library", "From my library", "Recast saved prompts from my prompt library", "Your saved prompts for this target, recast with your characters."],
];

function StatusChip({ label, status }) {
  const state = status === "valid" ? "success"
    : status === "failed" ? "failed"
    : ["repair_required", "duplicate_warning"].includes(status) ? "warning" : "pending";
  const Icon = state === "success" ? CircleCheck : state === "pending" ? Circle : CircleAlert;
  return <span className="dataset-status-chip" data-state={state} aria-label={`${label}: ${state}`}>
    <Icon size={13} aria-hidden="true" />{label}
  </span>;
}

function HelpDetails({ children }) {
  return <details className="dataset-help dataset-details">
    <summary><CircleHelp size={14} aria-hidden="true" />Learn more<ChevronDown size={14} aria-hidden="true" /></summary>
    <p className="mt-2 text-xs leading-relaxed text-muted">{children}</p>
  </details>;
}

function FailureReason({ item }) {
  if (!item.failure_reason && item.scene_status !== "failed" && item.prompt_status !== "failed") return null;
  return <p className={`${ui.warningNote} mt-2`} role="note" aria-label={`Prompt ${item.index} failure reason`}>
    <strong>{item.failure_stage === "prompt" ? "Prompt failed: " : "Scene planning failed: "}</strong>{item.failure_reason || "No failure details were recorded. Retry this item to get a fresh result."}
  </p>;
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
  targets, lengths, onGenerate, onCancel, onCopy, onReleaseJobs }) {
  const preferences = useWorkflowSettings("dataset");
  const { draft, update } = preferences;
  const [page, setPage] = useState("configure");
  const advancingJob = useRef("");
  const navigatedJob = useRef("");
  const availablePresets = orderDisplayPresets(presets || []);
  const director = availablePresets.find((item) => item.id === draft?.director_preset);
  const { starting, error, workflowActive, disabled,
    guidedLines, canPlanScenes, staleScenePlan, sceneUsable, validSceneCount, retryStage,
    canWrite, canContinue, remainingPromptCount, updateSceneSettings, updateWriterSettings,
    sceneAction, generateDataset, generateScenes, continueDataset, editResult, releaseCheckpoints, clearResults,
    confirmation, understanding, reviseConfirmation, cancelConfirmation, confirmRequest } = useDatasetWorkflow({ preferences, job, busy, active, noEngine,
      director, onGenerate: startGeneration, onReleaseJobs });
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

  const isGenerating = active && job?.kind === "dataset";
  const scenePlannerBusy = active && job?.kind === "dataset_scenes";
  const generationBusy = starting || isGenerating || scenePlannerBusy;
  const generationUnit = `prompt${draft?.amount === 1 ? "" : "s"}`;
  const showContinue = !!draft?.scene_plan.length && (draft.plan_scenes_first || remainingPromptCount > 0);

  useEffect(() => {
    if (active && job?.kind === "dataset" && navigatedJob.current !== job.id) {
      navigatedJob.current = job.id;
      advancingJob.current = job.id;
      setPage("scenes");
    }
    if (!advancingJob.current || job?.id !== advancingJob.current) return;
    const scenes = job.result?.scene_plan || [];
    if (job.status === "succeeded" || job.result?.completed > 0 || (scenes.length && scenes.every((row) =>
      ["valid", "failed", "repair_required"].includes(row.scene_status)))) {
      advancingJob.current = "";
      setPage("dataset");
      window.scrollTo({ top: 0 });
    } else if (["failed", "cancelled", "interrupted"].includes(job.status)) {
      advancingJob.current = "";
    }
  }, [job, active]);
  const triggerParts = draft?.trigger_connected === false
    ? draft.trigger.split(/(?:[,\n]+|\s+and\s+)/i).map((part) => part.trim()).filter(Boolean)
    : draft?.trigger.trim() ? [draft.trigger.trim()] : [];

  function exportDataset(name, content, type) {
    download(name, content, type);
    if (!workflowActive) void releaseCheckpoints();
  }

  const allText = draft?.results.map((item) => item.prompt).join("\n\n") || "";
  const jsonl = datasetJsonl(draft);
  const failedItems = draft?.scene_plan?.filter((item) => item.scene_status === "failed" || item.prompt_status === "failed") || [];
  const displayedResults = [...(draft?.results || []), ...failedItems.filter((item) => !draft.results.some((result) => result.index === item.index))
    .map((item) => ({ ...item, failed: true, prompt: "" }))].sort((left, right) => left.index - right.index);

  function exportGenerationLog() {
    download("dataset-generation-log.json", datasetGenerationLog({ draft, review: understanding, job, record: preferences.record,
      state: { active: workflowActive, starting, error, settings_status: preferences.status, settings_error: preferences.error,
        settings_conflict: preferences.conflict, stale_scene_plan: staleScenePlan, valid_scene_count: validSceneCount } }), "application/json;charset=utf-8");
  }

  function goToStep(step) {
    setPage(step);
    window.scrollTo({ top: 0 });
  }

  function continueToDataset() {
    if (remainingPromptCount) void continueDataset();
    else goToStep("dataset");
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

  async function startGeneration(operation, input) {
    const accepted = await onGenerate(operation, input);
    if (accepted && operation === "dataset/scene") navigatedJob.current = accepted.id;
    if (accepted && operation === "dataset/scenes") goToStep("scenes");
    if (accepted && operation === "dataset") {
      const planning = !input.input.scene_plan.length;
      navigatedJob.current = accepted.id;
      advancingJob.current = planning ? accepted.id : "";
      goToStep(planning ? "scenes" : "dataset");
    }
    return accepted;
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
      <span role="status" className="flex items-center gap-2">{workflowActive && <LoaderCircle size={15} className="dataset-loader" aria-hidden="true" />}{workflowActive ? job.status === "cancelling" ? "Ending batch…" : <>{job.progress || "Starting dataset generation…"}{stageSeconds >= 5 && ` · ${elapsedLabel(stageSeconds)}`}</> : `${draft?.results.length || 0} prompts in the current batch${failedItems.length ? ` · ${failedItems.length} failed` : ""}`}</span>
      {active && <button className={ui.button} onClick={onCancel} disabled={job.status === "cancelling"}>End generation</button>}
    </div>
    </div>
    {workflowActive && stageSeconds >= 45 && <p className={`${ui.subtleNote} mb-5`} role="status">
      {job.kind === "dataset" && !job.result?.completed ? "No prompt has completed yet. " : "The current model request is still running. "}
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
            <label className={ui.field}><span>Dataset idea</span>
              <textarea className={ui.ideaInput} aria-label="Dataset idea" maxLength={10000}
                value={draft.subject} onChange={(event) => updateSceneSettings({ subject: event.target.value })}
                placeholder="A woman doing funny stuff · a dog going on small adventures · a knight doing office work" />
            </label>
            <div className="dataset-subject-fields">
              <label className={ui.field}><span>Subject type</span>
              <select className={ui.select} aria-label="Subject type" value={draft.trigger_type}
                onChange={(event) => updateSceneSettings({ trigger_type: event.target.value })}>
                {triggerTypes.map((item) => <option key={item}>{item}</option>)}
              </select>
            </label>
              <label className={ui.field}><span>Amount</span>
                <select className={ui.select} aria-label="Number of prompts" value={draft.amount}
                  onChange={(event) => updateSceneSettings({ amount: Number(event.target.value) })}>
                  {Array.from({ length: 25 }, (_, index) => index + 1).map((amount) =>
                    <option key={amount} value={amount}>{amount}</option>)}
                </select>
              </label>
            </div>
            {draft.trigger_type === "Custom" && <label className={ui.field}><span>Custom subject kind</span>
              <input className={ui.input} aria-label="Custom subject kind" maxLength={120} value={draft.custom_type}
                onChange={(event) => updateSceneSettings({ custom_type: event.target.value })} placeholder="e.g. architecture language, mascot, material" />
            </label>}
             <label className={ui.field}><span><Tag size={14} aria-hidden="true" />Trigger text</span>
              <textarea className={`${ui.notesInput} dataset-trigger-input`} aria-label="Trigger text or terms" maxLength={1000} value={draft.trigger}
                onChange={(event) => updateWriterSettings({ trigger: event.target.value })} placeholder="e.g. old lady with dark hair · or woman, cake" />
               <small className={ui.directorDescription}>Exact wording to include in each prompt.</small>
             </label>
             <details className="dataset-details dataset-advanced">
               <summary><SlidersHorizontal size={14} aria-hidden="true" /><span>Advanced options</span>
                 {draft.constraints.trim() && <span className="dataset-rules-indicator">Rules added</span>}<ChevronDown size={14} aria-hidden="true" /></summary>
               <div className="dataset-config-fields mt-4">
                 <label className={ui.field}><span>Consistency and variation rules (optional)</span>
                   <textarea className={ui.notesInput} aria-label="Consistency and variation rules" maxLength={10000}
                     value={draft.constraints} onChange={(event) => updateSceneSettings({ constraints: event.target.value })}
                     placeholder="Same hairstyle and outfit. No outdoor scenes. Each image shows a different mishap…" />
                 </label>
             <details className="dataset-details rounded-lg border border-line p-3">
               <summary><Tag size={14} aria-hidden="true" /><span>Training trigger & controls</span><ChevronDown size={14} aria-hidden="true" /></summary>
               <div className="mt-4 grid gap-4">
            <div className="grid gap-2">
               <label className={ui.choiceCard}>
                 <input type="checkbox" className="mt-0.5" aria-label="Require trigger at beginning"
                  checked={draft.trigger_at_start === true} onChange={(event) => updateWriterSettings({ trigger_at_start: event.target.checked })} />
                 <span title="Beginning placement is a preference; it never makes an otherwise usable prompt fail."><strong className="block">Require trigger at beginning</strong>
                   <small className="mt-1 block leading-relaxed text-muted">Prefer the trigger before other details.</small></span>
              </label>
               <label className={ui.choiceCard}>
                 <input type="checkbox" className="mt-0.5" aria-label="Keep trigger text connected"
                  checked={draft.trigger_connected !== false} onChange={(event) => updateWriterSettings({ trigger_connected: event.target.checked })} />
                 <span title="Turn off to distribute comma-, line-, or ‘and’-separated terms. Grouping is a preference; exact wording is required when trigger expansion is off."><strong className="block">Keep trigger connected</strong>
                   <small className="mt-1 block leading-relaxed text-muted">Keep terms together, or distribute them.</small></span>
              </label>
              {draft.trigger_connected === false && triggerParts.length > 0 && <p className={ui.subtleNote}>
                {triggerParts.length === 1 ? "One required term detected. Add commas, new lines, or “and” to distribute multiple terms: " : "Required distributed terms: "}
                {triggerParts.map((part) => `“${part}”`).join(" · ")}
              </p>}
               <label className={ui.choiceCard}>
                 <input type="checkbox" className="mt-0.5" aria-label="Allow trigger expansion"
                  checked={draft.expand_trigger === true} onChange={(event) => updateWriterSettings({ expand_trigger: event.target.checked })} />
                 <span title="On: natural articles, capitalization and added descriptors are allowed while each subject stays mentioned. Off: preserve each trigger term exactly as typed and avoid unsolicited identity, appearance, design, material or style details. Explicit concept and rule requirements remain allowed."><strong className="block">Allow trigger expansion</strong>
                    <small className="mt-1 block leading-relaxed text-muted">On: expand wording. Off: keep exact trigger terms.</small></span>
              </label>
            </div>
              </div>
             </details>
                    <HelpDetails>Generate prompts starts fresh: confirm the request once, then ideas, scenes and prompts run automatically in order. Generate scenes only pauses for manual review; Continue keeps your approved plan and completed prompts, and generates only missing prompts. Repeated or invalid ideas are repaired once after valid work finishes, without discarding good results. Changed settings or expired approval need a new review. Scene edits are used as written. Ideas uses temporary recent-event history to avoid repeats; prompts follow the accepted scene.</HelpDetails>
               </div>
             </details>
          </fieldset>
        </section>

        <section className="dataset-config-column" aria-label="Dataset generation settings">
          <header className="dataset-config-heading">
            <h3>Model &amp; output settings</h3><p>Choose instructions and prompt format.</p>
          </header>
          <fieldset disabled={disabled}>
            <label className={ui.field}><span><SlidersHorizontal size={14} aria-hidden="true" />Director preset</span>
              <select className={ui.select} aria-label="Dataset director preset" value={draft.director_preset} onChange={(event) => updateWriterSettings({ director_preset: event.target.value })}>
                {!director && <option value={draft.director_preset}>Unavailable — choose a preset</option>}
                {availablePresets.map((item) => <option key={item.id} value={item.id}>{presetDisplayLabel(item)}</option>)}
              </select>
            </label>
            <div className="mt-4 grid grid-cols-2 gap-4 tiny:grid-cols-1">
              <TargetSelect label="Target model" ariaLabel="Dataset target model" icon={<Cpu size={14} aria-hidden="true" />} value={draft.target} targets={targets} disabled={disabled} onChange={(target) => updateWriterSettings({ target })} />
              <label className={ui.field}><span><AlignLeft size={14} aria-hidden="true" />Prompt length</span>
                <select className={ui.select} aria-label="Dataset prompt length" value={draft.length} onChange={(event) => updateWriterSettings({ length: event.target.value })}>
                  {lengths.map((item) => <option key={item}>{item}</option>)}
                </select>
              </label>
            </div>

            <div className="mt-4 grid grid-cols-2 gap-4 tiny:grid-cols-1">
              <label className={ui.field}><span><Sparkles size={14} aria-hidden="true" />Creativity</span>
                <select className={ui.select} aria-label="Dataset descriptive creativity" value={draft.creativity || "Balanced"} onChange={(event) => updateWriterSettings({ creativity: event.target.value })}>
                  {["Strict", "Balanced", "Creative", "Dice"].map((item) => <option key={item}>{item}</option>)}
                </select>
                <small className="text-xs leading-relaxed text-muted">Changes visual treatment, not the planned action.</small>
              </label>
              <label className={ui.field}><span><WandSparkles size={14} aria-hidden="true" />Style</span>
                <select className={ui.select} aria-label="Dataset visual style" value={draft.style || "Auto"} onChange={(event) => updateWriterSettings({ style: event.target.value })}>
                  {styles.map((item) => <option key={item}>{item}</option>)}
                </select>
                <small className="text-xs leading-relaxed text-muted">Auto follows your concept; with Anima it means anime.</small>
              </label>
            </div>

            <fieldset className="mt-5 border-t border-line pt-4">
              <legend className="pr-2 text-xs font-semibold">Scene source</legend>
              <div className="mt-2 grid grid-cols-3 gap-2 tiny:grid-cols-1">
                {sceneSources.map(([value, label, accessibleLabel]) =>
                   <label key={value} className={`${ui.choiceCard} block`}>
                     <span className="flex items-center gap-2 text-xs font-semibold"><input type="radio" name="dataset-source" value={value} aria-label={`${label}: ${accessibleLabel}`}
                       checked={draft.source_mode === value} onChange={() => updateSceneSettings({ source_mode: value })} />{label}</span>
                  </label>)}
              </div>
              <small className="mt-2 block text-xs leading-relaxed text-muted">{(sceneSources.find(([value]) => value === draft.source_mode) || sceneSources[0])[3]}</small>
              {draft.source_mode === "guided" && <label className={`${ui.field} mt-4`}><span>Guided inputs · one per line ({guidedLines})</span>
                <textarea className={ui.ideaInput} aria-label="Guided dataset inputs" maxLength={50000}
                  value={draft.inputs} onChange={(event) => updateSceneSettings({ inputs: event.target.value })}
                  placeholder={"standing portrait in a city at night\nrunning through a sunlit field\nclose-up profile in a quiet studio"} />
                   <small className={ui.directorDescription}>Lines cycle to fill the batch; each action stays fixed.</small>
              </label>}
              {draft.source_mode === "library" && <LibraryStatus target={draft.target} className="mt-4 block" />}
            </fieldset>

          </fieldset>
        </section>
      </div>
        <footer className="dataset-config-actions">
          <button className={ui.button} disabled={!canPlanScenes} onClick={generateScenes}>
            <Layers3 size={15} />Generate {draft.amount} {draft.amount === 1 ? "scene" : "scenes"} only
          </button>
          <div>
            {showContinue && <button className={ui.button} disabled={!canContinue}
              onClick={continueToDataset}><ArrowRight size={15} />Continue</button>}
            <button className={ui.primaryButton} disabled={!canWrite} onClick={generateDataset}>
              <Sparkles size={17} />{generationBusy ? "Generating" : "Generate"} {draft.amount} {generationUnit}{generationBusy ? "…" : ""}
            </button>
          </div>
        </footer>
      </section>}
      </div>

      <div id="dataset-scenes" role="tabpanel" aria-labelledby="dataset-tab-scenes" tabIndex={0} hidden={page !== "scenes"}>
      {page === "scenes" && <section className={`${ui.panel} dataset-scenes-panel`} aria-label="Scene Planner ideas">
        <header className={ui.panelHeader}>
          <div className={ui.panelIcon}><Layers3 size={21} /></div>
           <div className={ui.panelHeading}><h2>Ideas and scenes</h2>
             <p>Edit what happens and how it fits one image.</p></div>
        </header>
        {!draft.scene_plan.length ? <div className={`${ui.emptyState} dataset-empty`}>
          <Layers3 size={34} aria-hidden="true" /><h3>{scenePlannerBusy || isGenerating ? "Planning scenes…" : "No scenes yet"}</h3>
           <p>{scenePlannerBusy || isGenerating ? "Scenes will appear here as planning progresses." : "Set up your idea on Configure, then choose Generate."}</p>
          <button className={ui.button} onClick={() => goToStep("configure")}>Back to Configure</button>
        </div> : <>
        <HelpDetails>Each idea comes with its finished scene, and the final prompt is written from the scene. Edit the scene to change the image; edits invalidate only that prompt. Output settings reuse scenes and invalidate prompts.</HelpDetails>
        {staleScenePlan && <p className={ui.warningNote}>This plan no longer matches the Dataset settings. Generate fresh scenes before continuing.</p>}
        <div className="dataset-card-grid mt-4">
          {draft.scene_plan.map((item) => <article key={item.index} className="dataset-card dataset-scene-card" aria-label={`Scene ${item.index} card`}>
            <header className="dataset-card-header dataset-scene-header">
              <div className="dataset-scene-title"><Layers3 size={18} aria-hidden="true" />
                <h3>Scene <span>{String(item.index).padStart(2, "0")}</span></h3></div>
              <div className="dataset-status-group"><StatusChip label="Idea" status={item.idea_status || "valid"} />
                <StatusChip label="Scene" status={sceneUsable(item) ? "valid" : item.scene_status === "valid" ? "not_generated" : item.scene_status} />
                <StatusChip label="Prompt" status={item.prompt_status} /></div>
            </header>
            <div className="dataset-scene-body">
            <FailureReason item={item} />
            {item.input && <p className="dataset-scene-source">Original idea: {item.input}</p>}
            <div className="dataset-scene-editor dataset-scene-idea">
              <div className="dataset-scene-editor-heading"><label htmlFor={`dataset-idea-${item.index}`}><Lightbulb size={15} aria-hidden="true" />Idea {item.index}</label></div>
              <textarea className={ui.notesInput} aria-label={`Planned idea ${item.index}`} value={item.idea || ""}
                id={`dataset-idea-${item.index}`} placeholder="Describe this image's idea" disabled={disabled}
                maxLength={preferences.record?.idea_limits?.characters}
                onChange={(event) => update(editDatasetPlan(draft, item.index, "idea", event.target.value))} />
            </div>
            <div className="dataset-scene-editor dataset-scene-description">
              <div className="dataset-scene-editor-heading">
                <label htmlFor={`dataset-scene-${item.index}`}><AlignLeft size={15} aria-hidden="true" />Scene {item.index}</label>
              </div>
              <textarea className={ui.notesInput} aria-label={`Planned scene ${item.index}`} value={item.scene}
                id={`dataset-scene-${item.index}`} maxLength={preferences.record?.scene_limits?.characters} disabled={disabled}
                onChange={(event) => update(editDatasetPlan(draft, item.index, "scene", event.target.value))} />
            </div>
            </div>
            <footer className="dataset-scene-actions">
              <button className={ui.button} title="Regenerate idea" aria-label="Regenerate idea" disabled={!canWrite || staleScenePlan}
                onClick={() => sceneAction(item.index, "regenerate_idea")}><RefreshCw size={14} aria-hidden="true" />Regenerate idea</button>
              <button className={`${ui.button} dataset-scene-write`} title="Regenerate prompt" aria-label="Regenerate prompt" disabled={!canWrite || staleScenePlan || !sceneUsable(item)}
                onClick={() => sceneAction(item.index, "regenerate_prompt")}><WandSparkles size={14} aria-hidden="true" />Regenerate prompt</button>
            </footer>
          </article>)}
        </div>
        <div className="mt-4 flex flex-wrap gap-3">
          {showContinue && <button className={ui.primaryButton} disabled={!canContinue}
            onClick={continueToDataset}><ArrowRight size={15} />Continue</button>}
          <button className={ui.button} disabled={!canPlanScenes} onClick={generateScenes}><RefreshCw size={14} />Generate new scenes</button>
          <button className={ui.button} disabled={!draft.scene_plan.length}
             onClick={() => exportDataset("dataset-scenes.json", JSON.stringify(draft.scene_plan, null, 2), "application/json")}><FileJson size={14} />Scenes JSON</button>
        </div>
        </>}
      </section>}
      </div>

      <div id="dataset-dataset" role="tabpanel" aria-labelledby="dataset-tab-dataset" tabIndex={0} hidden={page !== "dataset"}>
      {page === "dataset" && <section aria-label="Dataset results">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <div><h3 className="font-display text-lg font-bold">Generated dataset</h3>
            <p className="mt-1 text-xs text-muted">Completed prompts appear as the batch runs and remain editable.</p></div>
          <div className="flex flex-wrap gap-2">
            <button className={ui.button} disabled={!draft.results.length} onClick={() => onCopy(datasetCopyText(draft))}><Copy size={15} />Copy all</button>
            <button className={ui.button} disabled={!draft.results.length} onClick={() => exportDataset("dataset-prompts.txt", allText, "text/plain;charset=utf-8")}><Download size={15} />TXT</button>
            <button className={ui.button} disabled={!draft.results.length} onClick={() => exportDataset("dataset-prompts.jsonl", jsonl, "application/x-ndjson;charset=utf-8")}><FileJson size={15} />JSONL</button>
            <button className={ui.button} disabled={disabled || !draft.results.length} onClick={clearResults}><Trash2 size={15} />Clear</button>
          </div>
        </div>
        {!displayedResults.length ? <div className={`${ui.emptyState} dataset-empty`}>
           <Database size={34} aria-hidden="true" /><h3>{isGenerating ? "Generating prompts…" : "No prompts yet"}</h3>
           <p>{isGenerating ? "Completed prompts will appear here as the batch runs." : "Generate prompts from Configure, or continue an existing plan from Scenes."}</p>
           {!isGenerating && <button className={ui.button} onClick={() => goToStep("configure")}>Back to Configure</button>}
        </div> : <div className="dataset-card-grid">
          {displayedResults.map((item) => {
            return <article className="dataset-card dataset-result-card panel" key={item.index}>
            <div className="dataset-card-header">
               <div><span className="text-sm font-semibold text-accent">Prompt {item.index}</span>
                {item.input && <p className="mt-1 max-w-[48ch] truncate text-[10px] text-muted" title={item.input}>{item.input}</p>}
                </div>
               <div className="dataset-status-group">{item.failed ? <StatusChip label="Failed · skipped" status="failed" /> : <StatusChip label="Generated" status="valid" />}</div>
             </div>
              {item.idea ? <div className="text-xs">
                <p className="whitespace-pre-wrap leading-relaxed text-muted">{item.idea}</p>
              </div> : <p className={`${ui.subtleNote} mb-3`}>Legacy result: no originating idea was saved.</p>}
              {item.scene ? <details className="dataset-details rounded-lg border border-line p-3 text-xs">
               <summary><Layers3 size={14} aria-hidden="true" /><span>Scene {item.index}</span><ChevronDown size={14} aria-hidden="true" /></summary>
               <p className="mt-2 whitespace-pre-wrap leading-relaxed text-muted">{item.scene}</p>
              </details> : <p className={`${ui.subtleNote} mb-3`}>Legacy result: no originating scene was saved.</p>}
              <FailureReason item={item} />
              {item.failed ? <button className={`${ui.button} mt-3`} disabled={!canWrite || staleScenePlan}
                onClick={() => sceneAction(item.index, `regenerate_${retryStage(item)}`)}><RefreshCw size={14} aria-hidden="true" />Retry failed {retryStage(item)}</button> : <>
              <label htmlFor={`dataset-prompt-${item.index}`} className="dataset-final-label">Final prompt</label>
              <textarea className={ui.outputInput} style={{ minHeight: 220 }} aria-label={`Dataset prompt ${item.index}`}
               id={`dataset-prompt-${item.index}`}
               value={item.prompt} maxLength={100000} disabled={disabled}
              onChange={(event) => editResult(item.index, event.target.value)} />
              <div><button className={ui.button} onClick={() => onCopy(item.prompt)}><Copy size={14} aria-hidden="true" />Copy</button></div>
              </>}
          </article>})}
        </div>}
      </section>}
      </div>
    </>}
    {confirmation && <DatasetConfirmationModal review={confirmation} busy={busy} onRevise={reviseConfirmation}
      onConfirm={confirmRequest} onCancel={cancelConfirmation} onExport={exportGenerationLog} />}
  </div>;
}
