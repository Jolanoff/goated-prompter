import { useEffect, useRef, useState } from "react";
import { AlignLeft, Box, ChevronDown, Circle, CircleAlert, CircleCheck, CircleHelp, Copy, Cpu, Database, Download, FileJson, Layers3, LoaderCircle, Palette, RefreshCw, ShieldCheck, SlidersHorizontal, Sparkles, Tag, Trash2, WandSparkles, Wrench, X, Zap } from "lucide-react";
import { ui } from "../ui.js";
import { api } from "../api.js";
import { orderDisplayPresets, presetDisplayLabel } from "../presetPresentation.js";
import { TargetSelect } from "./WorkflowControls.jsx";
import { useWorkflowSettings } from "./useWorkflowSettings.js";
import WorkflowSettingsStatus from "./WorkflowSettingsStatus.jsx";
import { datasetJsonl } from "./datasetExport.js";
import { editDatasetPlan, invalidateDatasetPrompts, isDatasetSceneUsable, datasetRetryStage } from "./datasetState.js";
import { geometryRows } from "./datasetGeometry.js";

const triggerTypes = ["Character", "Multiple characters", "Animal", "Object / product", "Visual style",
  "Location / environment", "Brand / logo", "Typography / text", "Concept", "Custom"];
const visualStyles = ["Photorealistic", "Cinematic photography", "Anime / manga", "Illustration", "3D render", "Graphic design", "Keep described style", "Mixed styles", "Custom"];
const varieties = ["Focused", "Balanced", "Wide"];
const metricLabels = {
  idea_uniqueness: "Idea diversity", scene_uniqueness: "Scene diversity",
  uniqueness: "Prompt diversity", trigger: "Trigger", format: "Format",
};
const metricOrder = Object.keys(metricLabels);

function StatusChip({ label, status }) {
  const state = ["valid", "generated", "pass", "strong"].includes(status) ? "success"
    : ["failed", "error"].includes(status) ? "failed"
    : ["warning", "geometry_warning", "duplicate_warning", "review", "issues"].includes(status) ? "warning" : "pending";
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

function GeometryButton({ geometry, index, onOpen }) {
  if (!geometryRows(geometry).length) return null;
  return <button className={`${ui.iconButton} dataset-geometry-button`} type="button"
    title={`View geometry ${index}`} aria-label={`View geometry ${index}`} aria-haspopup="dialog"
    onClick={() => onOpen({ geometry, index })}><Box size={18} aria-hidden="true" /></button>;
}

function GeometryModal({ item, onClose }) {
  const dialog = useRef(null);
  useEffect(() => {
    if (item && !dialog.current?.open) dialog.current?.showModal();
    else if (!item && dialog.current?.open) dialog.current.close();
  }, [item]);
  const rows = geometryRows(item?.geometry);
  return <dialog ref={dialog} className="app-dialog dataset-geometry-dialog"
    aria-labelledby="dataset-geometry-title" onCancel={(event) => { event.preventDefault(); onClose(); }} onClose={onClose}
    onKeyDown={(event) => {
      if (event.key !== "Tab") return;
      const controls = event.currentTarget.querySelectorAll('button, [tabindex="0"]');
      const first = controls[0], last = controls[controls.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    }}>
    <header className="mb-5 flex items-center gap-3 border-b border-line pb-4">
      <div className={ui.panelIcon}><Box size={21} aria-hidden="true" /></div>
      <h2 id="dataset-geometry-title" className="min-w-0 flex-1 font-display text-lg font-bold">Geometry {item?.index}</h2>
      <button className={`${ui.iconButton} dataset-geometry-button`} type="button" aria-label="Close geometry" title="Close geometry" onClick={onClose} autoFocus><X size={18} aria-hidden="true" /></button>
    </header>
    <dl className="dataset-geometry-fields gap-4 text-xs" tabIndex={0} aria-label={`Geometry ${item?.index} fields`}>{rows.map(({ label, value }) => <div key={label} className="min-w-0 content-start grid gap-1 rounded-lg border border-line p-3">
      <dt className="capitalize font-semibold">{label}</dt>
      <dd className="wrap-anywhere leading-relaxed text-muted">{value}</dd>
    </div>)}</dl>
  </dialog>;
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
  const [starting, setStarting] = useState(false);
  const [qualityBusy, setQualityBusy] = useState(false);
  const [error, setError] = useState("");
  const [geometryItem, setGeometryItem] = useState(null);
  const submission = useRef(false);
  const synced = useRef("");
  const qualityAttempt = useRef(0);
  const [clock, setClock] = useState(Date.now());

  useEffect(() => {
    if (!visible) setGeometryItem(null);
  }, [visible]);

  const datasetJob = ["dataset", "dataset_scenes", "dataset_review"].includes(job?.kind);
  const workflowActive = datasetJob && active;
  const stageSeconds = workflowActive
    ? Math.max(0, Math.floor(clock / 1000 - (job.progress_at || job.created_at || clock / 1000)))
    : 0;

  useEffect(() => {
    if (!workflowActive) return;
    setClock(Date.now());
    const timer = setInterval(() => setClock(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [workflowActive, job?.id, job?.progress_at]);

  useEffect(() => {
    if (!datasetJob || job.status !== "failed") return;
    setError(`${job.kind === "dataset_review" ? "Dataset review" : job.kind === "dataset_scenes" ? "Scene planning" : "Dataset generation"} failed. ${job.error || "The prompt engine did not return a usable result."}`);
  }, [datasetJob, job?.id, job?.revision, job?.status, job?.kind, job?.error]);

  useEffect(() => {
    if (!draft || !["dataset", "dataset_scenes"].includes(job?.kind) || !job.result?.scene_plan) return;
    const key = `${job.id}:${job.revision}`;
    if (synced.current === key) return;
    synced.current = key;
    update({
      ...(job.kind === "dataset" && Array.isArray(job.result.prompts) ? {
        results: job.result.prompts, result_job_id: job.id,
      } : {}),
      scene_plan: job.result.scene_plan,
      scene_plan_signature: job.result.scene_plan_signature,
      ...(job.result.quality_report ? { quality_report: job.result.quality_report } : {}),
    });
  }, [job, draft, update]);

  useEffect(() => {
    if (!draft || job?.kind !== "dataset_review" || job.status !== "succeeded" || !job.result?.report) return;
    const key = `review:${job.id}:${job.revision}`;
    if (synced.current === key) return;
    synced.current = key;
    update({ quality_report: job.result.report });
  }, [job, draft, update]);

  const disabled = busy || starting || preferences.working;
  const availablePresets = orderDisplayPresets(presets || []);
  const director = availablePresets.find((item) => item.id === draft?.director_preset);
  const guidedLines = draft?.inputs.split("\n").filter((line) => line.trim()).length || 0;
  const customReady = draft?.trigger_type !== "Custom" || draft.custom_type.trim();
  const styleReady = draft?.visual_style !== "Custom" || draft.custom_style.trim();
  const sourceReady = draft?.source_mode !== "guided" || guidedLines > 0;
  const canPlanScenes = draft && !disabled && !noEngine && !preferences.conflict &&
    draft.subject.trim() && customReady && styleReady && sourceReady;
  const staleScenePlan = !!draft?.scene_plan_signature && (preferences.record?.scene_plan_matches_settings ?? preferences.record?.idea_plan_current) === false &&
    preferences.record?.draft.scene_plan_signature === draft.scene_plan_signature;
  const validSceneCount = draft?.scene_plan?.filter(isDatasetSceneUsable).length || 0;
  const scenePlanReady = !staleScenePlan && !!draft?.scene_plan_signature && validSceneCount > 0;
  const canWrite = canPlanScenes && director && draft.trigger.trim();
  const canGenerate = canWrite && !draft.scene_plan?.some((item) => item.scene_status !== "failed" && item.idea !== undefined && !item.idea.trim());
  const isGenerating = active && job?.kind === "dataset";
  const scenePlannerBusy = active && job?.kind === "dataset_scenes";
  const triggerParts = draft?.trigger_connected === false
    ? draft.trigger.split(/(?:[,\n]+|\s+and\s+)/i).map((part) => part.trim()).filter(Boolean)
    : draft?.trigger.trim() ? [draft.trigger.trim()] : [];

  useEffect(() => {
    const attempt = ++qualityAttempt.current;
    let disposed = false;
    setQualityBusy(false);
    if (!draft?.results.length || workflowActive) return;
    if (draft.quality_report?.signature && draft.quality_report.idea_quality) return;
    const timer = setTimeout(async () => {
      setQualityBusy(true);
      try {
        const result = await api("/workspace/dataset/quality", { input: { ...draft, quality_report: {} } });
        if (disposed || qualityAttempt.current !== attempt) return;
        update({ quality_report: result.report });
      } catch (err) {
        if (!disposed && qualityAttempt.current === attempt) setError(`Could not analyze dataset quality. ${err.message}`);
      } finally {
        if (!disposed && qualityAttempt.current === attempt) setQualityBusy(false);
      }
    }, 500);
    return () => { disposed = true; clearTimeout(timer); };
  }, [draft, workflowActive, update]);

  function updateSceneSettings(patch) {
    update({ ...patch, scene_plan: [], scene_plan_signature: "", quality_report: {}, results: [] });
  }

  function updateWriterSettings(patch) {
    update(invalidateDatasetPrompts(draft, patch));
  }

  async function sceneAction(index, action) {
    if (disabled || staleScenePlan || !canWrite || submission.current) return;
    submission.current = true;
    setStarting(true);
    setError("");
    try {
      await preferences.flush();
      await onGenerate("dataset/scene", { input: draft, index, action });
    } catch (err) { setError(err.message); }
    finally { submission.current = false; setStarting(false); }
  }

  async function generate(scenesOnly = false, validOnly = false) {
    if (!(scenesOnly ? canPlanScenes : validOnly ? canWrite && scenePlanReady : canGenerate) || submission.current) return;
    submission.current = true;
    setStarting(true);
    setError("");
    try {
      let input = draft;
      if (!scenesOnly) {
        input = { ...input, results: [], result_job_id: "", quality_report: {} };
        update({ results: [], result_job_id: "", quality_report: {} });
      }
      await preferences.flush();
      await onGenerate(scenesOnly ? "dataset/scenes" : "dataset", { input, ...(validOnly ? { valid_only: true } : {}) });
    } catch (err) { setError(err.message); }
    finally { submission.current = false; setStarting(false); }
  }

  async function deepReview() {
    if (!draft?.results.length || disabled || noEngine || submission.current) return;
    submission.current = true;
    setStarting(true);
    setError("");
    try {
      await preferences.flush();
      await onGenerate("dataset/review", { input: draft });
    } catch (err) { setError(err.message); }
    finally { submission.current = false; setStarting(false); }
  }

  function editResult(index, prompt) {
    update({ results: draft.results.map((item) => item.index === index ? { ...item, prompt } : item), quality_report: {} });
  }

  async function releaseCheckpoints() {
    try {
      // Preserve existing draft autosave. Only disposable job checkpoints/logs
      // are released; exports never delete the editable scene plan or history.
      await preferences.flush();
      await onReleaseJobs?.("dataset");
    } catch (err) { setError(`Could not release temporary job checkpoints. ${err.message}`); }
  }

  function exportDataset(name, content, type) {
    download(name, content, type);
    if (!workflowActive) void releaseCheckpoints();
  }

  async function clearResults() {
    update({ results: [], result_job_id: "", quality_report: {} });
    await releaseCheckpoints();
  }

  const allText = draft?.results.map((item) => item.prompt).join("\n\n") || "";
  const jsonl = datasetJsonl(draft);
  const quality = draft?.quality_report;
  const qualityMetrics = Object.entries(quality?.metrics || {}).sort(([left], [right]) =>
    (metricOrder.includes(left) ? metricOrder.indexOf(left) : 99) - (metricOrder.includes(right) ? metricOrder.indexOf(right) : 99));
  const promptQuality = new Map((quality?.prompts || []).map((item) => [item.index, item]));
  const failedItems = draft?.scene_plan?.filter((item) => item.scene_status === "failed" || item.prompt_status === "failed") || [];
  const displayedResults = [...(draft?.results || []), ...failedItems.filter((item) => !draft.results.some((result) => result.index === item.index))
    .map((item) => ({ ...item, failed: true, prompt: "" }))].sort((left, right) => left.index - right.index);

  return <div className="dataset-view" hidden={!visible}>
    <div className={ui.pageHeading}><div>
      <h2>Build a prompt dataset</h2>
      <p>One concept, distinct scenes. Create up to 25 trigger-ready prompts for your training set.</p>
    </div></div>
    <WorkflowSettingsStatus settings={preferences} label="Dataset" />
    {error && <div className={ui.message} role="alert"><span>{error}</span></div>}
    <div className={ui.workflowStatus}>
      <span>{noEngine ? "Choose a prompt engine in Builder or Settings to generate." : `Engine: ${engineLabel}`}</span>
      <span role="status" className="flex items-center gap-2">{workflowActive && <LoaderCircle size={15} className="dataset-loader" aria-hidden="true" />}{workflowActive ? job.status === "cancelling" ? "Ending batch…" : <>{job.progress || "Starting dataset generation…"}{stageSeconds >= 5 && ` · ${elapsedLabel(stageSeconds)}`}</> : `${draft?.results.length || 0} prompts in the current batch${failedItems.length ? ` · ${failedItems.length} failed` : ""}`}</span>
      {active && <button className={ui.button} onClick={onCancel} disabled={job.status === "cancelling"}>End generation</button>}
    </div>
    {workflowActive && stageSeconds >= 45 && <p className={`${ui.subtleNote} mb-5`} role="status">
      {job.kind === "dataset" && !job.result?.completed ? "No prompt has completed yet. " : "The current model request is still running. "}
      A local model may still be loading or generating. If the engine stops responding, its configured timeout will produce an error here; you can end generation now without waiting.
    </p>}

    {draft && <>
      <div className="dataset-config-grid">
        <section className={ui.panel} aria-label="Dataset trigger and concept settings">
          <header className={ui.panelHeader}>
            <div className={ui.panelIcon}><Database size={21} /></div>
            <div className={ui.panelHeading}><h2>Dataset idea</h2><p>What should happen in these images?</p></div>
          </header>
          <fieldset disabled={disabled} className={ui.fields}>
            <label className={ui.field}><span>Dataset idea</span>
              <textarea className={ui.ideaInput} aria-label="Dataset idea" maxLength={10000}
                value={draft.subject} onChange={(event) => updateSceneSettings({ subject: event.target.value })}
                placeholder="A woman doing funny stuff · a dog going on small adventures · a knight doing office work" />
              <small className={ui.directorDescription}>Describe the subject and what makes these images different.</small>
            </label>
            <label className={ui.field}><span>Subject type</span>
              <select className={ui.select} aria-label="Subject type" value={draft.trigger_type}
                onChange={(event) => updateSceneSettings({ trigger_type: event.target.value })}>
                {triggerTypes.map((item) => <option key={item}>{item}</option>)}
              </select>
            </label>
            {draft.trigger_type === "Custom" && <label className={ui.field}><span>Custom subject kind</span>
              <input className={ui.input} aria-label="Custom subject kind" maxLength={120} value={draft.custom_type}
                onChange={(event) => updateSceneSettings({ custom_type: event.target.value })} placeholder="e.g. architecture language, mascot, material" />
            </label>}
            <div className="grid grid-cols-2 gap-4 tiny:grid-cols-1">
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
            <label className={ui.field}><span>Consistency and variation rules (optional)</span>
              <textarea className={ui.notesInput} aria-label="Consistency and variation rules" maxLength={10000}
                value={draft.constraints} onChange={(event) => updateSceneSettings({ constraints: event.target.value })}
                placeholder="Same hairstyle and outfit. No outdoor scenes. Each image shows a different mishap…" />
            </label>
            <label className={ui.field}><span>{draft.planning_mode === "Quality" ? <ShieldCheck size={14} aria-hidden="true" /> : <Zap size={14} aria-hidden="true" />}Planning mode</span>
              <select className={ui.select} aria-label="Dataset planning mode" value={draft.planning_mode || "Fast"}
                onChange={(event) => updateSceneSettings({ planning_mode: event.target.value })}>
                <option>Fast</option><option>Quality</option>
              </select>
               <small className={ui.directorDescription}>Fast — ideas and scenes together. Quality — ideas first, scenes second.</small>
            </label>
            <HelpDetails>Planning saves valid scenes as it goes. Failed items use local repair; valid siblings remain unchanged. You can retry skipped items individually.</HelpDetails>
             <label className={ui.field}><span><Tag size={14} aria-hidden="true" />Trigger text or terms</span>
              <textarea className={ui.notesInput} style={{ minHeight: 82 }} aria-label="Trigger text or terms" maxLength={200} value={draft.trigger}
                onChange={(event) => updateWriterSettings({ trigger: event.target.value })} placeholder="e.g. old lady with dark hair · or woman, cake" />
               <small className={ui.directorDescription}>Exact wording to include in each prompt.</small>
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
          </fieldset>
        </section>

        <section className={ui.panel} aria-label="Dataset generation settings">
          <header className={ui.panelHeader}>
            <div className={ui.panelIcon}><Sparkles size={21} /></div>
            <div className={ui.panelHeading}><h2>Prompt settings</h2><p>Choose the treatment and target.</p></div>
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
              <TargetSelect label="Dataset target model" icon={<Cpu size={14} aria-hidden="true" />} value={draft.target} targets={targets} disabled={disabled} onChange={(target) => updateWriterSettings({ target })} />
              <label className={ui.field}><span><AlignLeft size={14} aria-hidden="true" />Prompt length</span>
                <select className={ui.select} aria-label="Dataset prompt length" value={draft.length} onChange={(event) => updateWriterSettings({ length: event.target.value })}>
                  {lengths.map((item) => <option key={item}>{item}</option>)}
                </select>
              </label>
            </div>

            <fieldset className="mt-5 border-t border-line pt-4">
              <legend className="pr-2 text-xs font-semibold">Scene source</legend>
              <div className="mt-2 grid grid-cols-2 gap-2 tiny:grid-cols-1">
                {[['random', 'Let Scene Planner invent scenes', 'Distinct situations from your concept.'],
                  ['guided', 'Provide my own scene ideas', 'One idea per line; the action stays fixed.']].map(([value, label, help]) =>
                   <label key={value} className={`${ui.choiceCard} block`}>
                    <span className="flex items-center gap-2 text-xs font-semibold"><input type="radio" name="dataset-source" value={value}
                       checked={draft.source_mode === value} onChange={() => updateSceneSettings({ source_mode: value })} />{label}</span>
                    <small className="mt-2 block text-[10px] leading-relaxed text-muted">{help}</small>
                  </label>)}
              </div>
              {draft.source_mode === "guided" && <label className={`${ui.field} mt-4`}><span>Guided inputs · one per line ({guidedLines})</span>
                <textarea className={ui.ideaInput} style={{ minHeight: 160 }} aria-label="Guided dataset inputs" maxLength={50000}
                  value={draft.inputs} onChange={(event) => updateSceneSettings({ inputs: event.target.value })}
                  placeholder={"standing portrait in a city at night\nrunning through a sunlit field\nclose-up profile in a quiet studio"} />
                   <small className={ui.directorDescription}>Lines cycle to fill the batch; each action stays fixed.</small>
              </label>}
            </fieldset>

            <button className={`${ui.primaryButton} mt-5 w-full`} disabled={!canGenerate} onClick={() => generate(false)}>
              <Sparkles size={17} />{starting || isGenerating ? `Generating ${draft.amount} prompts…` : `Generate ${draft.amount} prompts`}
            </button>
            <button className={`${ui.button} mt-3 w-full justify-center`} disabled={!canPlanScenes}
              onClick={() => generate(true)}><Layers3 size={15} />{scenePlannerBusy ? "Planning scenes…" : "Plan scenes first"}</button>
              <p className={ui.subtleNote}>{!draft.subject.trim() ? "Add a dataset idea to get started." : !draft.trigger.trim() ? "Add trigger text, or plan scenes without it." : "Generate directly, or plan first to edit your scenes."}</p>
          </fieldset>
        </section>
      </div>

      {!!draft.scene_plan?.length && <section className={`${ui.panel} mt-6`} aria-label="Scene Planner ideas">
        <header className={ui.panelHeader}>
          <div className={ui.panelIcon}><Layers3 size={21} /></div>
          <div className={ui.panelHeading}><h2>Scene planner</h2>
             <p>Edit what happens and how it fits one image.</p></div>
        </header>
        <HelpDetails>Idea edits invalidate only that scene and prompt. Scene edits invalidate only that prompt. Output settings reuse the plan and invalidate prompts.</HelpDetails>
        {staleScenePlan && <p className={ui.warningNote}>This plan no longer matches the Dataset settings. Plan scenes again or use the main Generate action to replan automatically.</p>}
        <div className="dataset-card-grid mt-4">
          {draft.scene_plan.map((item) => <div key={item.index} className="dataset-card rounded-lg border border-line">
            <div className="dataset-card-header"><strong className="dataset-card-number">#{String(item.index).padStart(2, "0")}</strong>
              <div className="dataset-status-group"><StatusChip label="Idea" status={item.idea_status || "valid"} /><StatusChip label="Scene" status={item.scene_status || "valid"} /><StatusChip label="Prompt" status={item.prompt_status} /><GeometryButton geometry={item.geometry} index={item.index} onOpen={setGeometryItem} /></div>
            </div>
            <FailureReason item={item} />
            {item.input && <small className="text-muted">Original idea: {item.input}</small>}
            <label className={ui.field}><span>Idea {item.index}</span>
              <input className={ui.input} aria-label={`Planned idea ${item.index}`} value={item.idea || ""}
                placeholder="Legacy plan: replan to generate an idea" disabled={disabled}
                maxLength={preferences.record?.idea_limits?.characters}
                onChange={(event) => update(editDatasetPlan(draft, item.index, "idea", event.target.value))} />
            </label>
            <label className={ui.field}><span>Scene {item.index}</span>
              <textarea className={ui.notesInput} aria-label={`Planned scene ${item.index}`} value={item.scene}
                maxLength={preferences.record?.scene_limits?.characters} disabled={disabled}
                onChange={(event) => update(editDatasetPlan(draft, item.index, "scene", event.target.value))} />
            </label>
            <div className="flex flex-wrap gap-2">
              <button className={ui.button} title="Regenerate idea" aria-label="Regenerate idea" disabled={!canWrite || staleScenePlan}
                onClick={() => sceneAction(item.index, "regenerate_idea")}><RefreshCw size={14} aria-hidden="true" />Idea</button>
              <button className={ui.button} title="Repair scene" aria-label="Repair scene" disabled={!canWrite || staleScenePlan || !item.idea?.trim()}
                onClick={() => sceneAction(item.index, "repair_scene")}><Wrench size={14} aria-hidden="true" />Scene</button>
              <button className={ui.button} title="Regenerate prompt" aria-label="Regenerate prompt" disabled={!canWrite || staleScenePlan || !isDatasetSceneUsable(item)}
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

      {!!draft.results.length && <section className={`${ui.panel} mt-6`} aria-label="Dataset quality report">
        <header className={ui.panelHeader}>
          <div className={ui.panelIcon}>{quality?.status === "strong" ? <ShieldCheck size={21} /> : <CircleAlert size={21} />}</div>
          <div className={ui.panelHeading}><h2>Quality report</h2>
             <p>Check diversity, trigger wording and format.</p></div>
          <span className={ui.resultStatus} data-working={qualityBusy || active && job?.kind === "dataset_review"}><span className={ui.statusDot} />
            {active && job?.kind === "dataset_review" ? "Reviewing" : qualityBusy ? "Checking" : quality?.status === "strong" ? "Strong" : quality?.status === "review" ? "Needs review" : quality?.status === "issues" ? "Issues found" : "Pending"}
          </span>
        </header>
         <div className={`${ui.workflowStatus} mb-4`}>
           <span>{quality?.deep_review?.completed ? `Deep review complete · ${quality.deep_review.errors} errors · ${quality.deep_review.warnings} warnings` : "Optional model review of fidelity and consistency."}</span>
          <button className={ui.button} disabled={disabled || noEngine || !draft.results.length} onClick={deepReview}>
            <ShieldCheck size={14} />{active && job?.kind === "dataset_review" ? "Deep reviewing…" : quality?.deep_review?.completed ? "Run deep review again" : "Deep consistency review"}
          </button>
        </div>
        {quality?.metrics ? <>
          <div className="dataset-metrics">
             <div className="rounded-lg border border-line bg-selected p-4 mobile:col-span-2"><span className="text-xs text-muted">Overall</span><strong className="mt-1 block font-display text-2xl text-accent">{quality.score}</strong></div>
             {qualityMetrics.map(([key, value]) => <div key={key} className="rounded-lg border border-line bg-canvas p-4">
               <span className="text-xs text-muted">{metricLabels[key] || key.replaceAll("_", " ")}</span><strong className="mt-1 block font-display text-xl">{value}%</strong>
            </div>)}
          </div>
          {!!quality.batch_issues?.length && <div className="mt-4 grid gap-2">
            {quality.batch_issues.map((issue, index) => <p key={`${issue.code}-${index}`} className={issue.severity === "error" ? ui.warningNote : ui.subtleNote}>
              <strong className="mr-1">{issue.severity === "error" ? "Issue:" : "Review:"}</strong>{issue.message}
            </p>)}
          </div>}
           <details className="dataset-details mt-4 rounded-lg border border-line bg-canvas p-3 text-xs" open={(quality.prompts || []).some((item) => item.status !== "pass")}>
            <summary><ShieldCheck size={14} aria-hidden="true" /><span>Prompt checks · {(quality.prompts || []).filter((item) => item.status === "pass").length}/{quality.prompts?.length || 0} passed</span><ChevronDown size={14} aria-hidden="true" /></summary>
            <div className="mt-3 grid gap-2">{(quality.prompts || []).map((item) => <div key={item.index} className="flex items-start gap-2 border-t border-line pt-2 first:border-0 first:pt-0">
               {item.status === "pass" ? <CircleCheck size={15} className="text-success" /> : <CircleAlert size={15} className={item.status === "error" ? "text-danger" : "text-warning"} />}
              <div><strong>Prompt {item.index}</strong>
                {item.issues.length ? <ul className="mt-1 grid gap-1 text-[11px] leading-relaxed text-muted">{item.issues.map((issue, index) => <li key={`${issue.code}-${index}`}>{issue.message}</li>)}</ul>
                  : <p className="mt-1 text-[11px] text-muted">All automatic checks passed.</p>}
              </div>
            </div>)}</div>
          </details>
          <HelpDetails>Automatic checks are structural and lexical hints, not a guarantee of training quality. Deep Review handles nuanced semantic consistency.</HelpDetails>
        </> : <p className="text-xs text-muted">{qualityBusy ? "Analyzing the current batch…" : "The report will appear after generation."}</p>}
      </section>}

      <section className="mt-6" aria-label="Dataset results">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <div><h3 className="font-display text-lg font-bold">Generated dataset</h3>
            <p className="mt-1 text-xs text-muted">Completed prompts appear as the batch runs and remain editable.</p></div>
          <div className="flex flex-wrap gap-2">
            <button className={ui.button} disabled={!draft.results.length} onClick={() => onCopy(allText)}><Copy size={15} />Copy all</button>
            <button className={ui.button} disabled={!draft.results.length} onClick={() => exportDataset("dataset-prompts.txt", allText, "text/plain;charset=utf-8")}><Download size={15} />TXT</button>
            <button className={ui.button} disabled={!draft.results.length} onClick={() => exportDataset("dataset-prompts.jsonl", jsonl, "application/x-ndjson;charset=utf-8")}><FileJson size={15} />JSONL</button>
            <button className={ui.button} disabled={disabled || !draft.results.length} onClick={clearResults}><Trash2 size={15} />Clear</button>
          </div>
        </div>
        {!displayedResults.length ? <div className={`${ui.emptyState} min-h-[260px]`}>
           <Database size={34} /><h3>Your scenes start with an idea</h3><p>Describe your concept above. Plan scenes to review them first, or generate the full batch.</p>
        </div> : <div className="dataset-card-grid">
          {displayedResults.map((item) => {
            const check = promptQuality.get(item.index);
            return <article className="dataset-card dataset-result-card panel" key={item.index}>
            <div className="dataset-card-header">
               <div><span className="text-sm font-semibold text-accent">Prompt {item.index}</span>
                {item.input && <p className="mt-1 max-w-[48ch] truncate text-[10px] text-muted" title={item.input}>{item.input}</p>}
                </div>
               <div className="dataset-status-group">{item.failed ? <StatusChip label="Failed · skipped" status="failed" /> : <StatusChip label={check?.status === "pass" ? "Passed" : check ? `${check.issues.length} issues` : "Pending checks"} status={check?.status} />}<GeometryButton geometry={item.geometry} index={item.index} onOpen={setGeometryItem} /></div>
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
                onClick={() => sceneAction(item.index, datasetRetryStage(item) === "scene" ? "repair_scene" : `regenerate_${datasetRetryStage(item)}`)}><RefreshCw size={14} aria-hidden="true" />Retry failed {datasetRetryStage(item)}</button> : <>
              <label htmlFor={`dataset-prompt-${item.index}`} className="dataset-final-label">Final prompt</label>
              <textarea className={ui.outputInput} style={{ minHeight: 220 }} aria-label={`Dataset prompt ${item.index}`}
               id={`dataset-prompt-${item.index}`}
              value={item.prompt} maxLength={100000} disabled={isGenerating || active && job?.kind === "dataset_review"}
              onChange={(event) => editResult(item.index, event.target.value)} />
              <div><button className={ui.button} onClick={() => onCopy(item.prompt)}><Copy size={14} aria-hidden="true" />Copy</button></div>
              {!!check?.issues.length && <details className="dataset-details rounded-lg border border-line p-3 text-xs" open>
                <summary><CircleAlert size={14} aria-hidden="true" />Diagnostics<ChevronDown size={14} aria-hidden="true" /></summary>
                <ul className="mt-3 grid gap-2 text-muted">{check.issues.map((issue, index) => <li key={`${issue.code}-${index}`}>{issue.message}</li>)}</ul>
              </details>}</>}
          </article>})}
        </div>}
      </section>
    </>}
    <GeometryModal item={geometryItem} onClose={() => setGeometryItem(null)} />
  </div>;
}
