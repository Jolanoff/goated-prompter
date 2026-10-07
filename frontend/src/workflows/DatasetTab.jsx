import { useEffect, useState } from "react";
import { AlignLeft, ChevronDown, Circle, CircleAlert, CircleCheck, CircleHelp, Copy, Cpu, Database, Download, FileJson, Layers3, LoaderCircle, Palette, RefreshCw, SlidersHorizontal, Sparkles, Tag, Trash2, WandSparkles, Wrench } from "lucide-react";
import { ui } from "../ui.js";
import { orderDisplayPresets, presetDisplayLabel } from "../presetPresentation.js";
import { TargetSelect } from "./WorkflowControls.jsx";
import { useWorkflowSettings } from "./useWorkflowSettings.js";
import WorkflowSettingsStatus from "./WorkflowSettingsStatus.jsx";
import { datasetCopyText, datasetJsonl, datasetGenerationLog } from "./datasetExport.js";
import { editDatasetPlan } from "./datasetState.js";
import { useDatasetWorkflow } from "./useDatasetWorkflow.js";
import DatasetConfirmationModal from "./DatasetConfirmationModal.jsx";
import DatasetIdeaDetails, { DatasetSceneCheck } from "./DatasetIdeaDetails.jsx";

const triggerTypes = ["Character", "Multiple characters", "Animal", "Object / product", "Visual style",
  "Location / environment", "Brand / logo", "Typography / text", "Concept", "Custom"];
const visualStyles = ["Photorealistic", "Cinematic photography", "Anime / manga", "Illustration", "3D render", "Graphic design", "Keep described style", "Mixed styles", "Custom"];
const varieties = ["Focused", "Balanced", "Wide"];

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
  const availablePresets = orderDisplayPresets(presets || []);
  const director = availablePresets.find((item) => item.id === draft?.director_preset);
  const { starting, error, resettingIdeas, noveltyNotice, workflowActive, disabled,
    guidedLines, canPlanScenes, staleScenePlan, sceneUsable, validSceneCount, retryStage,
    scenePlanReady, canWrite, canGenerate, updateSceneSettings, updateWriterSettings,
    sceneAction, generate, editResult, releaseCheckpoints, clearResults,
    resetRecentIdeas, confirmation, understanding, reviseConfirmation, cancelConfirmation, confirmRequest } = useDatasetWorkflow({ preferences, job, busy, active, noEngine,
      director, onGenerate, onReleaseJobs });
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
  const currentStep = workflowActive ? job.kind === "dataset" ? "dataset" : job.kind === "dataset_scenes" ? "scenes" : "configure"
    : displayedResults.length ? "dataset" : draft?.scene_plan?.length ? "scenes" : "configure";

  function exportGenerationLog() {
    download("dataset-generation-log.json", datasetGenerationLog({ draft, review: understanding, job, record: preferences.record,
      state: { active: workflowActive, starting, error, settings_status: preferences.status, settings_error: preferences.error,
        settings_conflict: preferences.conflict, stale_scene_plan: staleScenePlan, valid_scene_count: validSceneCount,
        novelty_notice: noveltyNotice } }), "application/json;charset=utf-8");
  }

  function goToStep(step) {
    const section = document.getElementById(`dataset-${step}`);
    section?.scrollIntoView({ block: "start" });
    section?.focus({ preventScroll: true });
  }

  return <div className="dataset-view" hidden={!visible}>
    <div className={`${ui.pageHeading} dataset-heading`}><div>
      <h2>Build a prompt dataset</h2>
      <p>Configure your idea, review the scenes, and build your training set.</p>
    </div><button className={ui.button} onClick={exportGenerationLog} title="Download current state only. No log is saved automatically.">
      <Download size={15} aria-hidden="true" />Export generation log</button></div>
    <nav className="dataset-workflow" aria-label="Dataset workflow">
      <ol>{[["configure", "Configure"], ["scenes", "Scenes"], ["dataset", "Dataset"]].map(([step, label], index) =>
        <li key={step}><button type="button" aria-current={currentStep === step ? "step" : undefined}
          aria-label={`Step ${index + 1}: ${label}`}
          disabled={step === "configure" ? !draft : step === "scenes" ? !draft?.scene_plan?.length : !displayedResults.length}
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
      <section className="dataset-configuration" id="dataset-configure" tabIndex={-1} aria-label="Configure dataset">
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
              <label className={ui.field}><span>Variety</span>
                <select className={ui.select} aria-label="Dataset variety" value={draft.variety}
                  onChange={(event) => updateSceneSettings({ variety: event.target.value })}>
                  {varieties.map((item) => <option key={item}>{item}</option>)}
                </select>
              </label>
            </div>
            {draft.trigger_type === "Custom" && <label className={ui.field}><span>Custom subject kind</span>
              <input className={ui.input} aria-label="Custom subject kind" maxLength={120} value={draft.custom_type}
                onChange={(event) => updateSceneSettings({ custom_type: event.target.value })} placeholder="e.g. architecture language, mascot, material" />
            </label>}
             <label className={ui.field}><span><Tag size={14} aria-hidden="true" />Trigger text</span>
              <textarea className={`${ui.notesInput} dataset-trigger-input`} aria-label="Trigger text or terms" maxLength={200} value={draft.trigger}
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
                 <div className="flex flex-wrap items-center gap-2">
                   <button className={ui.button} disabled={disabled || resettingIdeas || !draft.subject.trim()} onClick={resetRecentIdeas}>
                     <RefreshCw size={14} />{resettingIdeas ? "Resetting…" : "Reset recent ideas"}
                   </button>
                   <small className="text-xs text-muted">Resets temporary novelty hints, not your current scenes.</small>
                 </div>
                 {noveltyNotice && <p className={ui.subtleNote} role="status">{noveltyNotice}</p>}
                 <HelpDetails>Plan scenes first creates fresh ideas with recent-idea novelty hints. Generate reuses checked scenes. Scene edits need a new check before enhancement; Repair scene requests one targeted attempt, leaving valid siblings unchanged. Novelty hints stay in RAM and expire automatically.</HelpDetails>
               </div>
             </details>
          </fieldset>
        </section>

        <section className="dataset-config-column" aria-label="Dataset generation settings">
          <header className="dataset-config-heading">
            <h3>Model &amp; output settings</h3><p>Choose the visual treatment and prompt format.</p>
          </header>
          <fieldset disabled={disabled}>
            <div className="grid grid-cols-2 gap-4 tiny:grid-cols-1">
              <label className={ui.field}><span><Palette size={14} aria-hidden="true" />Visual style</span>
                <select className={ui.select} aria-label="Visual style" value={draft.visual_style} onChange={(event) => updateSceneSettings({ visual_style: event.target.value })}>
                  {visualStyles.map((item) => <option key={item}>{item}</option>)}
                </select>
              </label>
              <label className={ui.field}><span><SlidersHorizontal size={14} aria-hidden="true" />Director preset</span>
                <select className={ui.select} aria-label="Dataset director preset" value={draft.director_preset} onChange={(event) => updateWriterSettings({ director_preset: event.target.value })}>
                  {!director && <option value={draft.director_preset}>Unavailable — choose a preset</option>}
                  {availablePresets.map((item) => <option key={item.id} value={item.id}>{presetDisplayLabel(item)}</option>)}
                </select>
              </label>
            </div>
            {draft.visual_style === "Custom" && <label className={`${ui.field} mt-4`}><span>Custom visual style</span>
              <input className={ui.input} aria-label="Custom visual style" maxLength={500} value={draft.custom_style}
                onChange={(event) => updateSceneSettings({ custom_style: event.target.value })} placeholder="Describe medium, realism, rendering, texture and finish…" />
            </label>}
            <div className="mt-4 grid grid-cols-2 gap-4 tiny:grid-cols-1">
              <TargetSelect label="Target model" ariaLabel="Dataset target model" icon={<Cpu size={14} aria-hidden="true" />} value={draft.target} targets={targets} disabled={disabled} onChange={(target) => updateWriterSettings({ target })} />
              <label className={ui.field}><span><AlignLeft size={14} aria-hidden="true" />Prompt length</span>
                <select className={ui.select} aria-label="Dataset prompt length" value={draft.length} onChange={(event) => updateWriterSettings({ length: event.target.value })}>
                  {lengths.map((item) => <option key={item}>{item}</option>)}
                </select>
              </label>
            </div>

            <label className={`${ui.field} mt-4`}><span><Sparkles size={14} aria-hidden="true" />Creativity</span>
              <select className={ui.select} aria-label="Dataset descriptive creativity" value={draft.creativity || "Balanced"} onChange={(event) => updateWriterSettings({ creativity: event.target.value })}>
                {["Strict", "Balanced", "Creative", "Dice"].map((item) => <option key={item}>{item}</option>)}
              </select>
              <small className="text-xs leading-relaxed text-muted">Changes visual treatment, not the planned action.</small>
            </label>

            <fieldset className="mt-5 border-t border-line pt-4">
              <legend className="pr-2 text-xs font-semibold">Scene source</legend>
              <div className="mt-2 grid grid-cols-2 gap-2 tiny:grid-cols-1">
                {[['random', 'Invent scenes', 'Let Scene Planner invent scenes', 'Distinct situations from your concept.'],
                  ['guided', 'Use my scene ideas', 'Provide my own scene ideas', 'One idea per line; the action stays fixed.']].map(([value, label, accessibleLabel, help]) =>
                   <label key={value} className={`${ui.choiceCard} block`}>
                     <span className="flex items-center gap-2 text-xs font-semibold"><input type="radio" name="dataset-source" value={value} aria-label={`${label}: ${accessibleLabel}`}
                       checked={draft.source_mode === value} onChange={() => updateSceneSettings({ source_mode: value })} />{label}</span>
                    <small className="mt-2 block text-xs leading-relaxed text-muted">{help}</small>
                  </label>)}
              </div>
              {draft.source_mode === "guided" && <label className={`${ui.field} mt-4`}><span>Guided inputs · one per line ({guidedLines})</span>
                <textarea className={ui.ideaInput} aria-label="Guided dataset inputs" maxLength={50000}
                  value={draft.inputs} onChange={(event) => updateSceneSettings({ inputs: event.target.value })}
                  placeholder={"standing portrait in a city at night\nrunning through a sunlit field\nclose-up profile in a quiet studio"} />
                   <small className={ui.directorDescription}>Lines cycle to fill the batch; each action stays fixed.</small>
              </label>}
            </fieldset>

          </fieldset>
        </section>
      </div>
        <footer className="dataset-config-actions">
          <p>{!draft.subject.trim() ? "Add a dataset idea to get started." : !draft.trigger.trim() ? "Add trigger text, or plan scenes without it." : "Generate directly, or plan first to edit your scenes."}</p>
          <div>
            <button className={ui.button} disabled={!canPlanScenes}
              onClick={() => generate(true)}><Layers3 size={15} />{scenePlannerBusy ? "Planning scenes…" : "Plan scenes first"}</button>
            <button className={ui.primaryButton} disabled={!canGenerate} onClick={() => generate(false)}>
              <Sparkles size={17} />{starting || isGenerating ? `Generating ${draft.amount} prompts…` : `Generate ${draft.amount} prompts`}
            </button>
          </div>
        </footer>
      </section>

      {!!draft.scene_plan?.length && <section className={`${ui.panel} mt-6 dataset-stage`} id="dataset-scenes" tabIndex={-1} aria-label="Scene Planner ideas">
        <header className={ui.panelHeader}>
          <div className={ui.panelIcon}><Layers3 size={21} /></div>
           <div className={ui.panelHeading}><h2>Ideas and scenes</h2>
             <p>Edit what happens and how it fits one image.</p></div>
        </header>
        <HelpDetails>Idea edits discard stale descriptions and invalidate that scene, check and prompt. Scene edits invalidate that check and prompt. Output settings reuse checked scenes and invalidate prompts.</HelpDetails>
        {staleScenePlan && <p className={ui.warningNote}>This plan no longer matches the Dataset settings. Plan scenes again or use the main Generate action to replan automatically.</p>}
        <div className="dataset-card-grid mt-4">
          {draft.scene_plan.map((item) => <div key={item.index} className="dataset-card rounded-lg border border-line">
            <div className="dataset-card-header"><strong className="dataset-card-number">#{String(item.index).padStart(2, "0")}</strong>
              <div className="dataset-status-group"><StatusChip label="Idea" status={item.idea_status || "valid"} /><StatusChip label="Scene" status={item.scene_status || "valid"} /><StatusChip label="Prompt" status={item.prompt_status} /></div>
            </div>
            <FailureReason item={item} />
            {item.input && <small className="text-muted">Original idea: {item.input}</small>}
            <label className={ui.field}><span>Idea {item.index}</span>
              <textarea className={ui.notesInput} aria-label={`Planned idea ${item.index}`} value={item.idea || ""}
                placeholder="Describe this image's idea" disabled={disabled}
                maxLength={preferences.record?.idea_limits?.characters}
                onChange={(event) => update(editDatasetPlan(draft, item.index, "idea", event.target.value))} />
            </label>
            <DatasetIdeaDetails item={item} />
            <label className={ui.field}><span>Scene {item.index}</span>
              <textarea className={ui.notesInput} aria-label={`Planned scene ${item.index}`} value={item.scene}
                maxLength={preferences.record?.scene_limits?.characters} disabled={disabled}
                onChange={(event) => update(editDatasetPlan(draft, item.index, "scene", event.target.value))} />
            </label>
            <DatasetSceneCheck item={item} />
            <div className="flex flex-wrap gap-2">
              <button className={ui.button} title="Regenerate idea" aria-label="Regenerate idea" disabled={!canWrite || staleScenePlan}
                onClick={() => sceneAction(item.index, "regenerate_idea")}><RefreshCw size={14} aria-hidden="true" />Idea</button>
              <button className={ui.button} title="Repair scene" aria-label="Repair scene" disabled={!canWrite || staleScenePlan || !item.idea?.trim()}
                onClick={() => sceneAction(item.index, "repair_scene")}><Wrench size={14} aria-hidden="true" />Scene</button>
              <button className={ui.button} title="Regenerate prompt" aria-label="Regenerate prompt" disabled={!canWrite || staleScenePlan || !sceneUsable(item)}
                onClick={() => sceneAction(item.index, "regenerate_prompt")}><WandSparkles size={14} aria-hidden="true" />Prompt</button>
            </div>
          </div>)}
        </div>
        <div className="mt-4 flex flex-wrap gap-3">
          <button className={ui.primaryButton} disabled={!canWrite || !scenePlanReady}
            onClick={() => generate(false, true)}>{validSceneCount === draft.amount ? "Generate prompts from these scenes" : `Generate prompts from ${validSceneCount} valid ${validSceneCount === 1 ? "scene" : "scenes"}`}</button>
          <button className={ui.button} disabled={!canPlanScenes} onClick={() => generate(true)}><RefreshCw size={14} />Replan scenes</button>
          <button className={ui.button} disabled={!draft.scene_plan.length}
             onClick={() => exportDataset("dataset-scenes.json", JSON.stringify(draft.scene_plan, null, 2), "application/json")}><FileJson size={14} />Scenes JSON</button>
        </div>
      </section>}

      <section className="mt-6 dataset-stage" id="dataset-dataset" tabIndex={-1} aria-label="Dataset results">
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
           <Database size={34} /><h3>Your scenes start with an idea</h3><p>Describe your concept above. Plan scenes to review them first, or generate the full batch.</p>
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
                onClick={() => sceneAction(item.index, retryStage(item) === "scene" ? "repair_scene" : `regenerate_${retryStage(item)}`)}><RefreshCw size={14} aria-hidden="true" />Retry failed {retryStage(item)}</button> : <>
              <label htmlFor={`dataset-prompt-${item.index}`} className="dataset-final-label">Final prompt</label>
              <textarea className={ui.outputInput} style={{ minHeight: 220 }} aria-label={`Dataset prompt ${item.index}`}
               id={`dataset-prompt-${item.index}`}
               value={item.prompt} maxLength={100000} disabled={disabled}
              onChange={(event) => editResult(item.index, event.target.value)} />
              <div><button className={ui.button} onClick={() => onCopy(item.prompt)}><Copy size={14} aria-hidden="true" />Copy</button></div>
              </>}
          </article>})}
        </div>}
      </section>
    </>}
    {confirmation && <DatasetConfirmationModal review={confirmation} busy={busy} onRevise={reviseConfirmation}
      onConfirm={confirmRequest} onCancel={cancelConfirmation} onExport={exportGenerationLog} />}
  </div>;
}
