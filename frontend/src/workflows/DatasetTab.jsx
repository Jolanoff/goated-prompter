import { useEffect, useRef, useState } from "react";
import { CircleAlert, CircleCheck, Copy, Database, Download, FileJson, RefreshCw, ShieldCheck, Shuffle, Sparkles, Trash2 } from "lucide-react";
import { ui } from "../ui.js";
import { api } from "../api.js";
import { orderDisplayPresets, presetDisplayLabel } from "../presetPresentation.js";
import { TargetSelect } from "./WorkflowControls.jsx";
import { useWorkflowSettings } from "./useWorkflowSettings.js";
import WorkflowSettingsStatus from "./WorkflowSettingsStatus.jsx";
import { datasetJsonl } from "./datasetExport.js";
import { editDatasetPlan, invalidateDatasetPrompts, isDatasetSceneUsable } from "./datasetState.js";
import { geometryRows } from "./datasetGeometry.js";

const triggerTypes = ["Character", "Multiple characters", "Animal", "Object / product", "Visual style",
  "Location / environment", "Brand / logo", "Typography / text", "Concept", "Custom"];
const visualStyles = ["Photorealistic", "Cinematic photography", "Anime / manga", "Illustration", "3D render", "Graphic design", "Keep described style", "Mixed styles", "Custom"];
const varieties = ["Focused", "Balanced", "Wide"];
const axisLabels = {
  framing: "Framing", viewpoint: "Viewpoint", pose_action: "Pose / action", expression: "Expression",
  lighting: "Lighting", setting: "Setting", subject_matter: "Subject matter", composition: "Composition",
  scale: "Scale", palette: "Palette", context: "Use context", surface: "Surface", background: "Background",
  application: "Application", material: "Material", placement: "Placement", layout: "Layout", hierarchy: "Hierarchy",
};
const categoryAxes = {
  Character: ["framing", "viewpoint", "lighting", "setting", "pose_action", "expression"],
  "Multiple characters": ["framing", "viewpoint", "lighting", "setting", "pose_action", "expression"],
  Animal: ["framing", "viewpoint", "pose_action", "context", "lighting", "setting"],
  "Visual style": ["subject_matter", "composition", "scale", "palette", "lighting", "setting"],
  "Object / product": ["framing", "viewpoint", "context", "surface", "lighting", "background"],
  "Location / environment": ["viewpoint", "composition", "scale", "lighting", "setting", "context"],
  "Brand / logo": ["application", "material", "placement", "layout", "lighting", "setting"],
  "Typography / text": ["layout", "hierarchy", "material", "placement", "background", "lighting"],
  Concept: ["framing", "viewpoint", "composition", "context", "lighting", "setting"],
  Custom: ["framing", "viewpoint", "composition", "context", "lighting", "setting"],
};
const varietyAxisCounts = { Focused: 3, Balanced: 5, Wide: 6 };

function GeometryDetails({ geometry, index }) {
  const rows = geometryRows(geometry);
  if (!rows.length) return null;
  return <details className="dataset-geometry min-w-0 rounded-lg border border-line p-3 text-xs">
    <summary className="cursor-pointer font-semibold">Geometry {index}</summary>
    <dl className="dataset-geometry-fields mt-3 gap-3" tabIndex={0} aria-label={`Geometry ${index} fields`}>{rows.map(({ label, value }) => <div key={label} className="min-w-0 content-start grid gap-1">
      <dt className="capitalize font-semibold">{label}</dt>
      <dd className="wrap-anywhere leading-relaxed text-muted">{value}</dd>
    </div>)}</dl>
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
  targets, lengths, onGenerate, onCancel, onCopy }) {
  const preferences = useWorkflowSettings("dataset");
  const { draft, update } = preferences;
  const [starting, setStarting] = useState(false);
  const [coverageBusy, setCoverageBusy] = useState(false);
  const [qualityBusy, setQualityBusy] = useState(false);
  const [error, setError] = useState("");
  const submission = useRef(false);
  const synced = useRef("");
  const qualityAttempt = useRef(0);
  const [clock, setClock] = useState(Date.now());

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
  }, [datasetJob, job?.id, job?.revision, job?.status]);

  useEffect(() => {
    if (!draft || !["dataset", "dataset_scenes"].includes(job?.kind) || !job.result?.scene_plan) return;
    const key = `${job.id}:${job.revision}`;
    if (synced.current === key) return;
    synced.current = key;
    const coverage = job.result.coverage;
    update({
      ...(job.kind === "dataset" && Array.isArray(job.result.prompts) ? {
        results: job.result.prompts, result_job_id: job.id,
      } : {}),
      scene_plan: job.result.scene_plan,
      scene_plan_signature: job.result.scene_plan_signature,
      ...(coverage?.enabled ? { coverage_plan: coverage.plan, plan_signature: coverage.signature,
        plan_seed: coverage.seed, coverage_axes: coverage.selected_axes } : {}),
      ...(job.result.quality_report ? { quality_report: job.result.quality_report } : {}),
    });
  }, [job?.id, job?.revision, !!draft]);

  useEffect(() => {
    if (!draft || job?.kind !== "dataset_review" || job.status !== "succeeded" || !job.result?.report) return;
    const key = `review:${job.id}:${job.revision}`;
    if (synced.current === key) return;
    synced.current = key;
    update({ quality_report: job.result.report });
  }, [job?.id, job?.revision, !!draft]);

  const disabled = busy || starting || coverageBusy || preferences.working;
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
  const coverageEnabled = draft?.coverage_enabled === true;
  const allowedAxes = categoryAxes[draft?.trigger_type] || categoryAxes.Custom;
  const defaultAxes = allowedAxes.slice(0, ["Character", "Multiple characters"].includes(draft?.trigger_type)
    ? 4 : varietyAxisCounts[draft?.variety] || 5);
  const selectedAxes = draft?.coverage_axes?.length ? draft.coverage_axes.filter((key) => allowedAxes.includes(key)) : defaultAxes;
  const triggerParts = draft?.trigger_connected === false
    ? draft.trigger.split(/(?:[,\n]+|\s+and\s+)/i).map((part) => part.trim()).filter(Boolean)
    : draft?.trigger.trim() ? [draft.trigger.trim()] : [];

  useEffect(() => {
    const attempt = ++qualityAttempt.current;
    setQualityBusy(false);
    if (!draft?.results.length || workflowActive) return;
    if (draft.quality_report?.signature && draft.quality_report.idea_quality) return;
    const timer = setTimeout(async () => {
      setQualityBusy(true);
      try {
        const result = await api("/workspace/dataset/quality", { input: { ...draft, quality_report: {} } });
        if (qualityAttempt.current !== attempt) return;
        update({ quality_report: result.report,
          ...(result.coverage.enabled ? { coverage_plan: result.coverage.plan,
            plan_signature: result.coverage.signature, plan_seed: result.coverage.seed,
            coverage_axes: result.coverage.selected_axes } : {}) });
      } catch (err) {
        if (qualityAttempt.current === attempt) setError(`Could not analyze dataset quality. ${err.message}`);
      } finally {
        if (qualityAttempt.current === attempt) setQualityBusy(false);
      }
    }, 500);
    return () => { clearTimeout(timer); qualityAttempt.current++; };
  }, [draft?.results, draft?.quality_report?.signature, workflowActive]);

  function updatePlanning(patch) {
    update({ ...patch, coverage_plan: [], plan_signature: "", quality_report: {},
      scene_plan: [], scene_plan_signature: "", results: [] });
  }

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

  async function createPlan(shuffle = false) {
    if (!draft || coverageBusy || isGenerating) return null;
    setCoverageBusy(true);
    setError("");
    try {
      const currentSeed = Number.isInteger(draft.plan_seed) ? draft.plan_seed : 0;
      const input = { ...draft, coverage_enabled: true,
        plan_seed: shuffle ? (currentSeed + 1) % 2147483648 : currentSeed,
        coverage_axes: selectedAxes, coverage_plan: [], plan_signature: "", quality_report: {} };
      const coverage = await api("/workspace/dataset/coverage", { input });
      const patch = { plan_seed: coverage.seed, coverage_axes: coverage.selected_axes,
         coverage_plan: coverage.plan, plan_signature: coverage.signature, quality_report: {},
         ...(shuffle ? { scene_plan: [], scene_plan_signature: "" } : {}) };
      update(patch);
      return { ...input, ...patch };
    } catch (err) {
      setError(`Could not create the coverage plan. ${err.message}`);
      return null;
    } finally { setCoverageBusy(false); }
  }

  async function generate(scenesOnly = false, validOnly = false) {
    if (!(scenesOnly ? canPlanScenes : validOnly ? canWrite && scenePlanReady : canGenerate) || submission.current) return;
    submission.current = true;
    setStarting(true);
    setError("");
    try {
      let input = draft;
      if (coverageEnabled && (!draft.coverage_plan?.length || draft.coverage_plan.length !== draft.amount)) {
        input = await createPlan(false);
        if (!input) return;
      }
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

  const allText = draft?.results.map((item) => item.prompt).join("\n\n") || "";
  const jsonl = datasetJsonl(draft);
  const quality = draft?.quality_report;
  const promptQuality = new Map((quality?.prompts || []).map((item) => [item.index, item]));
  const failedItems = draft?.scene_plan?.filter((item) => item.scene_status === "failed" || item.prompt_status === "failed") || [];
  const displayedResults = [...(draft?.results || []), ...failedItems.filter((item) => !draft.results.some((result) => result.index === item.index))
    .map((item) => ({ ...item, failed: true, prompt: "" }))].sort((left, right) => left.index - right.index);

  return <div hidden={!visible}>
    <div className={ui.pageHeading}><div>
      <h2>Build a prompt dataset</h2>
      <p>One concept, distinct scenes. Create up to 25 trigger-ready prompts for your training set.</p>
    </div></div>
    <WorkflowSettingsStatus settings={preferences} label="Dataset" />
    {error && <div className={ui.message} role="alert"><span>{error}</span></div>}
    <div className={ui.workflowStatus}>
      <span>{noEngine ? "Choose a prompt engine in Builder or Settings to generate." : `Engine: ${engineLabel}`}</span>
      <span role="status">{workflowActive ? job.status === "cancelling" ? "Ending batch…" : <>{job.progress || "Starting dataset generation…"}{stageSeconds >= 5 && ` · ${elapsedLabel(stageSeconds)}`}</> : `${draft?.results.length || 0} prompts in the current batch${failedItems.length ? ` · ${failedItems.length} failed` : ""}`}</span>
      {active && <button className={ui.button} onClick={onCancel} disabled={job.status === "cancelling"}>End generation</button>}
    </div>
    {workflowActive && stageSeconds >= 45 && <p className={`${ui.subtleNote} mb-5`} role="status">
      {job.kind === "dataset" && !job.result?.completed ? "No prompt has completed yet. " : "The current model request is still running. "}
      A local model may still be loading or generating. If the engine stops responding, its configured timeout will produce an error here; you can end generation now without waiting.
    </p>}

    {draft && <>
      <div className="grid grid-cols-[minmax(260px,0.9fr)_minmax(0,1.2fr)] items-start gap-6 [@media(width<=850px)]:grid-cols-1">
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
              <small className={ui.directorDescription}>Describe the subject and overall concept. Scene Planner invents distinct visible situations, not just new backgrounds.</small>
            </label>
            <label className={ui.field}><span>Subject type</span>
              <select className={ui.select} aria-label="Subject type" value={draft.trigger_type}
                onChange={(event) => updatePlanning({ trigger_type: event.target.value, coverage_axes: [] })}>
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
                  onChange={(event) => updatePlanning({ amount: Number(event.target.value) })}>
                  {Array.from({ length: 25 }, (_, index) => index + 1).map((amount) =>
                    <option key={amount} value={amount}>{amount}</option>)}
                </select>
              </label>
              <label className={ui.field}><span>Variety</span>
                <select className={ui.select} aria-label="Dataset variety" value={draft.variety}
                  onChange={(event) => updatePlanning({ variety: event.target.value, coverage_axes: [] })}>
                  {varieties.map((item) => <option key={item}>{item}</option>)}
                </select>
              </label>
            </div>
            <label className={ui.field}><span>Consistency and variation rules (optional)</span>
              <textarea className={ui.notesInput} aria-label="Consistency and variation rules" maxLength={10000}
                value={draft.constraints} onChange={(event) => updateSceneSettings({ constraints: event.target.value })}
                placeholder="Same hairstyle and outfit. No outdoor scenes. Each image shows a different mishap…" />
            </label>
            <label className={ui.field}><span>Planning mode</span>
              <select className={ui.select} aria-label="Dataset planning mode" value={draft.planning_mode || "Fast"}
                onChange={(event) => updateSceneSettings({ planning_mode: event.target.value })}>
                <option>Fast</option><option>Quality</option>
              </select>
               <small className={ui.directorDescription}>Fast: combined ideas and scenes in small chunks. Quality: distinct ideas first, then scenes in small chunks. Valid chunks are saved. After three failed fixes, try one new idea, then skip the item if it still fails.</small>
            </label>
             <label className={ui.field}><span>Trigger text or terms</span>
              <textarea className={ui.notesInput} style={{ minHeight: 82 }} aria-label="Trigger text or terms" maxLength={200} value={draft.trigger}
                onChange={(event) => updateWriterSettings({ trigger: event.target.value })} placeholder="e.g. old lady with dark hair · or woman, cake" />
              <small className={ui.directorDescription}>The exact required text. When distributed, separate terms with commas or new lines.</small>
             </label>
             <details className="rounded-lg border border-line p-3">
               <summary className="cursor-pointer text-xs font-semibold">Training trigger & controls</summary>
               <div className="mt-4 grid gap-4">
            <div className="grid gap-2">
               <label className={ui.choiceCard}>
                 <input type="checkbox" className="mt-0.5" aria-label="Require trigger at beginning"
                  checked={draft.trigger_at_start === true} onChange={(event) => updateWriterSettings({ trigger_at_start: event.target.checked })} />
                <span><strong className="block">Require trigger at the beginning</strong>
                  <small className="mt-1 block leading-relaxed text-muted">On strongly requests beginning placement. Off encourages a natural introduction first. Placement will never make an otherwise usable prompt fail.</small></span>
              </label>
               <label className={ui.choiceCard}>
                 <input type="checkbox" className="mt-0.5" aria-label="Keep trigger text connected"
                  checked={draft.trigger_connected !== false} onChange={(event) => updateWriterSettings({ trigger_connected: event.target.checked })} />
                <span><strong className="block">Keep trigger text connected</strong>
                  <small className="mt-1 block leading-relaxed text-muted">Off requests comma-, line-, or “and”-separated terms in different positions. Missing wording or grouping is reported as a warning; finished prompts are not discarded.</small></span>
              </label>
              {draft.trigger_connected === false && triggerParts.length > 0 && <p className={ui.subtleNote}>
                {triggerParts.length === 1 ? "One required term detected. Add commas, new lines, or “and” to distribute multiple terms: " : "Required distributed terms: "}
                {triggerParts.map((part) => `“${part}”`).join(" · ")}
              </p>}
               <label className={ui.choiceCard}>
                 <input type="checkbox" className="mt-0.5" aria-label="Allow trigger expansion"
                  checked={draft.expand_trigger === true} onChange={(event) => updateWriterSettings({ expand_trigger: event.target.checked })} />
                <span><strong className="block">Allow the model to expand the trigger</strong>
                  <small className="mt-1 block leading-relaxed text-muted">Off prevents unsolicited identity, appearance, design, material, or style details. Explicit concept and rule requirements are still allowed.</small></span>
              </label>
            </div>
              </div>
            </details>
          </fieldset>
        </section>

        <section className={ui.panel} aria-label="Dataset generation settings">
          <header className={ui.panelHeader}>
            <div className={ui.panelIcon}><Sparkles size={21} /></div>
            <div className={ui.panelHeading}><h2>Prompt settings</h2><p>Choose the final treatment and target. Reuse scene ideas across targets.</p></div>
          </header>
          <fieldset disabled={disabled}>
            <div className="grid grid-cols-2 gap-4 tiny:grid-cols-1">
              <label className={ui.field}><span>Visual style</span>
                <select className={ui.select} aria-label="Visual style" value={draft.visual_style} onChange={(event) => updatePlanning({ visual_style: event.target.value })}>
                  {visualStyles.map((item) => <option key={item}>{item}</option>)}
                </select>
              </label>
              <label className={ui.field}><span>Director preset</span>
                <select className={ui.select} aria-label="Dataset director preset" value={draft.director_preset} onChange={(event) => updateWriterSettings({ director_preset: event.target.value })}>
                  {!director && <option value={draft.director_preset}>Unavailable — choose a preset</option>}
                  {availablePresets.map((item) => <option key={item.id} value={item.id}>{presetDisplayLabel(item)}</option>)}
                </select>
              </label>
            </div>
            {draft.visual_style === "Custom" && <label className={`${ui.field} mt-4`}><span>Custom visual style</span>
              <input className={ui.input} aria-label="Custom visual style" maxLength={500} value={draft.custom_style}
                onChange={(event) => updatePlanning({ custom_style: event.target.value })} placeholder="Describe medium, realism, rendering, texture and finish…" />
            </label>}
            <div className="mt-4 grid grid-cols-2 gap-4 tiny:grid-cols-1">
              <TargetSelect label="Dataset target model" value={draft.target} targets={targets} disabled={disabled} onChange={(target) => updateWriterSettings({ target })} />
              <label className={ui.field}><span>Prompt length</span>
                <select className={ui.select} aria-label="Dataset prompt length" value={draft.length} onChange={(event) => updateWriterSettings({ length: event.target.value })}>
                  {lengths.map((item) => <option key={item}>{item}</option>)}
                </select>
              </label>
            </div>

            <fieldset className="mt-5 border-t border-line pt-4">
              <legend className="pr-2 text-xs font-semibold">Scene source</legend>
              <div className="mt-2 grid grid-cols-2 gap-2 tiny:grid-cols-1">
                {[['random', 'Let Scene Planner invent scenes', 'Give Scene Planner the overall Dataset concept and it will create distinct visual situations.'],
                  ['guided', 'Provide my own scene ideas', 'Enter one idea per line. Scene Planner improves each idea without replacing its central action.']].map(([value, label, help]) =>
                   <label key={value} className={`${ui.choiceCard} block`}>
                    <span className="flex items-center gap-2 text-xs font-semibold"><input type="radio" name="dataset-source" value={value}
                       checked={draft.source_mode === value} onChange={() => updatePlanning({ source_mode: value })} />{label}</span>
                    <small className="mt-2 block text-[10px] leading-relaxed text-muted">{help}</small>
                  </label>)}
              </div>
              {draft.source_mode === "guided" && <label className={`${ui.field} mt-4`}><span>Guided inputs · one per line ({guidedLines})</span>
                <textarea className={ui.ideaInput} style={{ minHeight: 160 }} aria-label="Guided dataset inputs" maxLength={50000}
                  value={draft.inputs} onChange={(event) => updatePlanning({ inputs: event.target.value })}
                  placeholder={"standing portrait in a city at night\nrunning through a sunlit field\nclose-up profile in a quiet studio"} />
                  <small className={ui.directorDescription}>Lines cycle to fill the requested amount. Full scenes or partial place/pose/outfit ideas are welcome. Each line applies only to its own images; stated actions stay fixed.</small>
              </label>}
            </fieldset>

            <section className="mt-5 border-t border-line pt-4" aria-label="Coverage planner">
               <details className="rounded-lg border border-line bg-canvas p-3">
                <summary className="cursor-pointer text-xs font-semibold">Advanced coverage planning (optional)</summary>
                <p className="mt-3 text-[11px] leading-relaxed text-muted">Off by default. When off, your concept, romance or action rules, and guided inputs control the batch without automatic facet assignments.</p>
                 <label className={`${ui.choiceCard} mt-4`}>
                   <input type="checkbox" className="mt-0.5" aria-label="Use coverage plan"
                    checked={coverageEnabled} onChange={(event) => updateSceneSettings({ coverage_enabled: event.target.checked })} />
                  <span><strong className="block">Use coverage plan</strong>
                    <small className="mt-1 block leading-relaxed text-muted">Adds optional framing, viewpoint, lighting, and other category-specific cues. Pose/expression axes are soft requests; Scene Planner chooses action-compatible staging. User instructions always take priority.</small></span>
                </label>
                {!coverageEnabled && draft.coverage_plan?.length > 0 && <p className={ui.subtleNote}>Your saved {draft.coverage_plan.length}-row plan is preserved but will be ignored.</p>}
                {coverageEnabled && <>
                  <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
                    <span className="text-[11px] font-medium">Optional coverage controls</span>
                    <div className="flex gap-2">
                      <button type="button" className={ui.button} disabled={coverageBusy || isGenerating}
                        onClick={() => createPlan(false)}><RefreshCw size={14} />{coverageBusy ? "Planning coverage…" : "Create plan"}</button>
                      <button type="button" className={ui.button} disabled={coverageBusy || isGenerating || !draft.coverage_plan?.length}
                        onClick={() => createPlan(true)}><Shuffle size={14} />Shuffle</button>
                    </div>
                  </div>
                  <fieldset className="mt-4" disabled={disabled}>
                    <legend className="text-[11px] font-medium">Coverage axes</legend>
                    <div className="mt-2 flex flex-wrap gap-2">
                      {allowedAxes.map((key) => <label key={key}
                         className={ui.choiceChip}>
                         <input type="checkbox" aria-label={`Coverage axis ${axisLabels[key]}`}
                          checked={selectedAxes.includes(key)} onChange={(event) => {
                            const next = event.target.checked ? [...selectedAxes, key] : selectedAxes.filter((item) => item !== key);
                            if (next.length) updatePlanning({ coverage_axes: allowedAxes.filter((item) => next.includes(item)) });
                          }} />
                        {axisLabels[key]}
                      </label>)}
                    </div>
                  </fieldset>
                   {draft.coverage_plan?.length ? <div className="mt-4 overflow-x-auto rounded-lg border border-line"
                     tabIndex={0} role="region" aria-label="Dataset coverage assignments">
                     <table className="w-full min-w-[720px] border-collapse text-left text-xs">
                       <thead className="bg-canvas text-muted"><tr>
                        <th className="px-3 py-2.5">#</th>
                        {draft.source_mode === "guided" && <th className="px-3 py-2.5">Guided input</th>}
                        {Object.keys(draft.coverage_plan[0]?.facets || {}).map((key) => <th key={key} className="px-3 py-2.5">{axisLabels[key] || key}</th>)}
                      </tr></thead>
                       <tbody>{draft.coverage_plan.map((row) => <tr key={row.index} className="border-t border-line text-ink">
                         <td className="px-3 py-2.5 font-semibold text-accent">{row.index}</td>
                        {draft.source_mode === "guided" && <td className="max-w-48 truncate px-3 py-2.5" title={row.input}>{row.input}</td>}
                        {Object.entries(row.facets).map(([key, value]) => <td key={key} className="px-3 py-2.5">{value}</td>)}
                      </tr>)}</tbody>
                    </table>
                  </div> : <p className={ui.subtleNote}>No plan yet. Create one to preview the optional assignments; generation can also create it automatically.</p>}
                </>}
              </details>
            </section>
            <button className={`${ui.primaryButton} mt-5 w-full`} disabled={!canGenerate} onClick={() => generate(false)}>
              <Sparkles size={17} />{starting || isGenerating ? `Generating ${draft.amount} prompts…` : `Generate ${draft.amount} prompts`}
            </button>
            <button className={`${ui.button} mt-3 w-full justify-center`} disabled={!canPlanScenes}
              onClick={() => generate(true)}><Sparkles size={15} />{scenePlannerBusy ? "Planning scenes…" : "Plan scenes first"}</button>
             <p className={ui.subtleNote}>{!draft.subject.trim() ? "Add a dataset idea to get started. " : !draft.trigger.trim() ? "Add trigger text to generate final prompts, or plan scenes without it. " : "One-click generation plans automatically. "}Planning first lets you edit ideas before writing prompts.</p>
          </fieldset>
        </section>
      </div>

      {!!draft.scene_plan?.length && <section className={`${ui.panel} mt-6`} aria-label="Scene Planner ideas">
        <header className={ui.panelHeader}>
          <div className={ui.panelIcon}><Sparkles size={21} /></div>
          <div className={ui.panelHeading}><h2>Scene Planner ideas</h2>
             <p>Idea = what happens. Scene = how it fits one image. Target and prompt length changes reuse both.</p></div>
        </header>
        <p className={ui.subtleNote}>Idea edits invalidate only that scene and prompt. Scene edits invalidate only that prompt. Output settings keep the plan and invalidate prompts.</p>
        {staleScenePlan && <p className={ui.warningNote}>This plan no longer matches the Dataset settings. Plan scenes again or use the main Generate action to replan automatically.</p>}
        <div className="grid grid-cols-2 items-start gap-4 mobile:grid-cols-1">
          {draft.scene_plan.map((item) => <div key={item.index} className="min-w-0 grid content-start gap-3 rounded-lg border border-line p-3">
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
            <small className="text-muted">Idea: {item.idea_status || "valid"} · Scene: {item.scene_status || "valid"} · Prompt: {item.prompt_status || "not_generated"}</small>
            <GeometryDetails geometry={item.geometry} index={item.index} />
            <FailureReason item={item} />
            {!!item.coverage_conflicts?.length && <small className="text-muted">Incompatible coverage omitted: {item.coverage_conflicts.join(", ")}</small>}
            <div className="flex flex-wrap gap-2">
              <button className={ui.button} disabled={!canWrite || staleScenePlan}
                onClick={() => sceneAction(item.index, "regenerate_idea")}>Regenerate idea</button>
              <button className={ui.button} disabled={!canWrite || staleScenePlan || !item.idea?.trim()}
                onClick={() => sceneAction(item.index, "repair_scene")}>Repair scene</button>
              <button className={ui.button} disabled={!canWrite || staleScenePlan || !isDatasetSceneUsable(item)}
                onClick={() => sceneAction(item.index, "regenerate_prompt")}>Regenerate prompt</button>
            </div>
          </div>)}
        </div>
        <div className="mt-4 flex flex-wrap gap-3">
          <button className={ui.primaryButton} disabled={!canWrite || !scenePlanReady}
            onClick={() => generate(false, true)}>{validSceneCount === draft.amount ? "Generate prompts from these scenes" : `Generate prompts from ${validSceneCount} valid ${validSceneCount === 1 ? "scene" : "scenes"}`}</button>
          <button className={ui.button} disabled={!canPlanScenes} onClick={() => generate(true)}><RefreshCw size={14} />Replan scenes</button>
          <button className={ui.button} disabled={!draft.scene_plan.length}
            onClick={() => download("dataset-scenes.json", JSON.stringify(draft.scene_plan, null, 2), "application/json")}><FileJson size={14} />Scenes JSON</button>
        </div>
      </section>}

      {!!draft.results.length && <section className={`${ui.panel} mt-6`} aria-label="Dataset quality report">
        <header className={ui.panelHeader}>
          <div className={ui.panelIcon}>{quality?.status === "strong" ? <ShieldCheck size={21} /> : <CircleAlert size={21} />}</div>
          <div className={ui.panelHeading}><h2>Dataset quality report</h2>
             <p>Diagnostics for triggers, format, idea/scene similarity and explicit geometry conflicts{coverageEnabled ? ", plus optional planned coverage (not achieved coverage)" : ""}.</p></div>
          <span className={ui.resultStatus} data-working={qualityBusy || active && job?.kind === "dataset_review"}><span className={ui.statusDot} />
            {active && job?.kind === "dataset_review" ? "Reviewing" : qualityBusy ? "Checking" : quality?.status === "strong" ? "Strong" : quality?.status === "review" ? "Needs review" : quality?.status === "issues" ? "Issues found" : "Pending"}
          </span>
        </header>
         <div className={`${ui.workflowStatus} mb-4`}>
           <span>{quality?.deep_review?.completed ? `Deep review complete · ${quality.deep_review.errors} errors · ${quality.deep_review.warnings} warnings` : "Optional: check planned-scene fidelity, identity, style, constraints and achieved coverage with the prompt engine."}</span>
          <button className={ui.button} disabled={disabled || noEngine || !draft.results.length} onClick={deepReview}>
            <ShieldCheck size={14} />{active && job?.kind === "dataset_review" ? "Deep reviewing…" : quality?.deep_review?.completed ? "Run deep review again" : "Deep consistency review"}
          </button>
        </div>
        {quality?.metrics ? <>
          <div className={`grid ${coverageEnabled ? "grid-cols-5" : "grid-cols-4"} gap-3 mobile:grid-cols-2`}>
             <div className="rounded-lg border border-line bg-selected p-4 mobile:col-span-2"><span className="text-xs text-muted">Overall</span><strong className="mt-1 block font-display text-2xl text-accent">{quality.score}</strong></div>
             {Object.entries(quality.metrics).map(([key, value]) => <div key={key} className="rounded-lg border border-line bg-canvas p-4">
               <span className="text-xs capitalize text-muted">{key === "coverage" ? "Planned coverage" : key.replaceAll("_", " ")}</span><strong className="mt-1 block font-display text-xl">{value}%</strong>
            </div>)}
          </div>
          {!!quality.batch_issues?.length && <div className="mt-4 grid gap-2">
            {quality.batch_issues.map((issue, index) => <p key={`${issue.code}-${index}`} className={issue.severity === "error" ? ui.warningNote : ui.subtleNote}>
              <strong className="mr-1">{issue.severity === "error" ? "Issue:" : "Review:"}</strong>{issue.message}
            </p>)}
          </div>}
           <details className="mt-4 rounded-lg border border-line bg-canvas p-3 text-xs">
            <summary className="cursor-pointer font-semibold">Prompt checks · {(quality.prompts || []).filter((item) => item.status === "pass").length}/{quality.prompts?.length || 0} passed</summary>
            <div className="mt-3 grid gap-2">{(quality.prompts || []).map((item) => <div key={item.index} className="flex items-start gap-2 border-t border-line pt-2 first:border-0 first:pt-0">
               {item.status === "pass" ? <CircleCheck size={15} className="text-success" /> : <CircleAlert size={15} className={item.status === "error" ? "text-danger" : "text-warning"} />}
              <div><strong>Prompt {item.index}</strong>
                {item.issues.length ? <ul className="mt-1 grid gap-1 text-[11px] leading-relaxed text-muted">{item.issues.map((issue, index) => <li key={`${issue.code}-${index}`}>{issue.message}</li>)}</ul>
                  : <p className="mt-1 text-[11px] text-muted">All automatic checks passed.</p>}
              </div>
            </div>)}</div>
          </details>
          <p className={ui.subtleNote}>This report catches structural and similarity problems; it is a diagnostic, not a guarantee of training quality.</p>
        </> : <p className="text-xs text-muted">{qualityBusy ? "Analyzing the current batch…" : "The report will appear after generation."}</p>}
      </section>}

      <section className="mt-6" aria-label="Dataset results">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <div><h3 className="font-display text-lg font-bold">Generated dataset</h3>
            <p className="mt-1 text-xs text-muted">Completed prompts appear as the batch runs and remain editable.</p></div>
          <div className="flex flex-wrap gap-2">
            <button className={ui.button} disabled={!draft.results.length} onClick={() => onCopy(allText)}><Copy size={15} />Copy all</button>
            <button className={ui.button} disabled={!draft.results.length} onClick={() => download("dataset-prompts.txt", allText, "text/plain;charset=utf-8")}><Download size={15} />TXT</button>
            <button className={ui.button} disabled={!draft.results.length} onClick={() => download("dataset-prompts.jsonl", jsonl, "application/x-ndjson;charset=utf-8")}><FileJson size={15} />JSONL</button>
            <button className={ui.button} disabled={disabled || !draft.results.length} onClick={() => update({ results: [], result_job_id: "", quality_report: {} })}><Trash2 size={15} />Clear</button>
          </div>
        </div>
        {!displayedResults.length ? <div className={`${ui.emptyState} min-h-[260px]`}>
           <Database size={34} /><h3>Your scenes start with an idea</h3><p>Describe your concept above. Plan scenes to review them first, or generate the full batch.</p>
        </div> : <div className="grid grid-cols-2 items-start gap-4 [@media(width<=1050px)]:grid-cols-1">
          {displayedResults.map((item) => {
            const check = promptQuality.get(item.index);
            return <article className={ui.panel} key={item.index}>
            <div className="mb-3 flex items-center justify-between gap-3">
               <div><span className="text-sm font-semibold text-accent">Prompt {item.index}</span>
                {item.input && <p className="mt-1 max-w-[48ch] truncate text-[10px] text-muted" title={item.input}>{item.input}</p>}
                 {check && <span className={`mt-1 inline-flex items-center gap-1 text-xs ${check.status === "pass" ? "text-success" : check.status === "error" ? "text-danger" : "text-warning"}`}>
                  {check.status === "pass" ? <CircleCheck size={11} /> : <CircleAlert size={11} />}{check.status === "pass" ? "Passed checks" : `${check.issues.length} ${check.issues.length === 1 ? "issue" : "issues"}`}
                </span>}</div>
               {!item.failed && <button className={ui.button} onClick={() => onCopy(item.prompt)}><Copy size={14} />Copy</button>}
               {item.failed && <span className="text-xs font-semibold text-warning">Failed · skipped</span>}
             </div>
              {item.idea ? <div className="mb-3 text-xs"><strong>Idea {item.index}</strong>
                <p className="mt-1 whitespace-pre-wrap leading-relaxed text-muted">{item.idea}</p>
              </div> : <p className={`${ui.subtleNote} mb-3`}>Legacy result: no originating idea was saved.</p>}
              {item.scene ? <details className="mb-3 rounded-lg border border-line p-3 text-xs" open>
               <summary className="cursor-pointer font-semibold">Scene {item.index}</summary>
               <p className="mt-2 whitespace-pre-wrap leading-relaxed text-muted">{item.scene}</p>
              </details> : <p className={`${ui.subtleNote} mb-3`}>Legacy result: no originating scene was saved.</p>}
              <GeometryDetails geometry={item.geometry} index={item.index} />
              <FailureReason item={item} />
              {item.failed ? <button className={`${ui.button} mt-3`} disabled={!canWrite || staleScenePlan}
                onClick={() => sceneAction(item.index, isDatasetSceneUsable(item) ? "regenerate_prompt" : "regenerate_idea")}>Retry failed {isDatasetSceneUsable(item) ? "prompt" : "idea"}</button> : <>
              <p className="mb-2 text-xs font-semibold">Final prompt</p>
             <textarea className={ui.outputInput} style={{ minHeight: 220 }} aria-label={`Dataset prompt ${item.index}`}
              value={item.prompt} maxLength={100000} disabled={isGenerating || active && job?.kind === "dataset_review"}
              onChange={(event) => editResult(item.index, event.target.value)} /></>}
          </article>})}
        </div>}
      </section>
    </>}
  </div>;
}
