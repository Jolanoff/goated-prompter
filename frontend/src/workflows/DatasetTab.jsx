import { useEffect, useRef, useState } from "react";
import { CircleAlert, CircleCheck, Copy, Database, Download, FileJson, RefreshCw, ShieldCheck, Shuffle, Sparkles, Trash2 } from "lucide-react";
import { ui } from "../ui.js";
import { api } from "../api.js";
import { orderDisplayPresets, presetDisplayLabel } from "../presetPresentation.js";
import { TargetSelect } from "./WorkflowControls.jsx";
import { useWorkflowSettings } from "./useWorkflowSettings.js";
import WorkflowSettingsStatus from "./WorkflowSettingsStatus.jsx";

const triggerTypes = ["Character", "Visual style", "Object / product", "Brand / logo", "Typography / text", "Custom"];
const visualStyles = ["Photorealistic", "Cinematic photography", "Anime / manga", "Illustration", "3D render", "Graphic design", "Keep described style", "Mixed styles", "Custom"];
const varieties = ["Focused", "Balanced", "Wide"];
const axisLabels = {
  framing: "Framing", viewpoint: "Viewpoint", pose_action: "Pose / action", expression: "Expression",
  lighting: "Lighting", setting: "Setting", subject_matter: "Subject matter", composition: "Composition",
  scale: "Scale", palette: "Palette", context: "Use context", surface: "Surface", background: "Background",
  application: "Application", material: "Material", placement: "Placement", layout: "Layout", hierarchy: "Hierarchy",
};
const categoryAxes = {
  Character: ["framing", "viewpoint", "pose_action", "expression", "lighting", "setting"],
  "Visual style": ["subject_matter", "composition", "scale", "palette", "lighting", "setting"],
  "Object / product": ["framing", "viewpoint", "context", "surface", "lighting", "background"],
  "Brand / logo": ["application", "material", "placement", "layout", "lighting", "setting"],
  "Typography / text": ["layout", "hierarchy", "material", "placement", "background", "lighting"],
  Custom: ["framing", "viewpoint", "composition", "context", "lighting", "setting"],
};
const varietyAxisCounts = { Focused: 3, Balanced: 5, Wide: 6 };

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
  const [plannerBusy, setPlannerBusy] = useState(false);
  const [qualityBusy, setQualityBusy] = useState(false);
  const [error, setError] = useState("");
  const submission = useRef(false);
  const synced = useRef("");
  const qualityAttempt = useRef(0);
  const [clock, setClock] = useState(Date.now());

  const datasetJob = job?.kind === "dataset" || job?.kind === "dataset_review";
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
    setError(`${job.kind === "dataset_review" ? "Dataset review" : "Dataset generation"} failed. ${job.error || "The prompt engine did not return a usable result."}`);
  }, [datasetJob, job?.id, job?.revision, job?.status]);

  useEffect(() => {
    if (!draft || job?.kind !== "dataset" || !Array.isArray(job.result?.prompts)) return;
    const key = `${job.id}:${job.revision}`;
    if (synced.current === key) return;
    synced.current = key;
    const coverage = job.result.coverage;
    update({
      results: job.result.prompts,
      result_job_id: job.id,
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

  const disabled = busy || starting || plannerBusy || preferences.working;
  const availablePresets = orderDisplayPresets(presets || []);
  const director = availablePresets.find((item) => item.id === draft?.director_preset);
  const guidedLines = draft?.inputs.split("\n").filter((line) => line.trim()).length || 0;
  const customReady = draft?.trigger_type !== "Custom" || draft.custom_type.trim();
  const styleReady = draft?.visual_style !== "Custom" || draft.custom_style.trim();
  const sourceReady = draft?.source_mode !== "guided" || guidedLines > 0;
  const canGenerate = draft && !disabled && !noEngine && !preferences.conflict && director &&
    draft.trigger.trim() && draft.subject.trim() && customReady && styleReady && sourceReady;
  const isGenerating = active && job?.kind === "dataset";
  const coverageEnabled = draft?.coverage_enabled === true;
  const allowedAxes = categoryAxes[draft?.trigger_type] || categoryAxes.Custom;
  const defaultAxes = allowedAxes.slice(0, varietyAxisCounts[draft?.variety] || 5);
  const selectedAxes = draft?.coverage_axes?.length ? draft.coverage_axes.filter((key) => allowedAxes.includes(key)) : defaultAxes;

  useEffect(() => {
    if (!draft?.results.length || isGenerating || job?.kind === "dataset" && active) return;
    if (draft.quality_report?.signature) return;
    const attempt = ++qualityAttempt.current;
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
    return () => clearTimeout(timer);
  }, [draft?.results, draft?.quality_report?.signature, isGenerating]);

  function updatePlanning(patch) {
    update({ ...patch, coverage_plan: [], plan_signature: "", quality_report: {} });
  }

  async function createPlan(shuffle = false) {
    if (!draft || plannerBusy || isGenerating) return null;
    setPlannerBusy(true);
    setError("");
    try {
      const currentSeed = Number.isInteger(draft.plan_seed) ? draft.plan_seed : 0;
      const input = { ...draft, coverage_enabled: true,
        plan_seed: shuffle ? (currentSeed + 1) % 2147483648 : currentSeed,
        coverage_axes: selectedAxes, coverage_plan: [], plan_signature: "", quality_report: {} };
      const coverage = await api("/workspace/dataset/plan", { input });
      const patch = { plan_seed: coverage.seed, coverage_axes: coverage.selected_axes,
        coverage_plan: coverage.plan, plan_signature: coverage.signature, quality_report: {} };
      update(patch);
      return { ...input, ...patch };
    } catch (err) {
      setError(`Could not create the coverage plan. ${err.message}`);
      return null;
    } finally { setPlannerBusy(false); }
  }

  async function generate() {
    if (!canGenerate || submission.current) return;
    submission.current = true;
    setStarting(true);
    setError("");
    try {
      let input = draft;
      if (coverageEnabled && (!draft.coverage_plan?.length || draft.coverage_plan.length !== draft.amount)) {
        input = await createPlan(false);
        if (!input) return;
      }
      input = { ...input, results: [], result_job_id: "", quality_report: {} };
      update({ results: [], result_job_id: "", quality_report: {} });
      await preferences.flush();
      await onGenerate("dataset", { input });
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
  const jsonl = draft?.results.map((item) => JSON.stringify({ prompt: item.prompt, trigger: draft.trigger,
    target: draft.target, source: item.input || null })).join("\n") || "";
  const quality = draft?.quality_report;
  const promptQuality = new Map((quality?.prompts || []).map((item) => [item.index, item]));

  return <div hidden={!visible}>
    <div className={ui.pageHeading}><div>
      <div className={ui.eyebrow}>CONSISTENT CONCEPT. USEFUL VARIATION.</div>
      <h2>Build a prompt <span>dataset.</span></h2>
      <p>Create up to 25 trigger-ready prompts for character, style, product, brand, text, or custom training sets.</p>
    </div></div>
    <WorkflowSettingsStatus settings={preferences} label="Dataset" />
    {error && <div className={ui.message} role="alert"><span>{error}</span></div>}
    <div className="mb-5 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-line px-4 py-3 text-xs text-muted">
      <span>{noEngine ? "Choose a prompt engine in Builder or Settings to generate." : `Engine: ${engineLabel}`}</span>
      <span role="status">{workflowActive ? job.status === "cancelling" ? "Ending batch…" : <>{job.progress || "Starting dataset generation…"}{stageSeconds >= 5 && ` · ${elapsedLabel(stageSeconds)}`}</> : `${draft?.results.length || 0} prompts in the current batch`}</span>
      {active && <button className={ui.button} onClick={onCancel} disabled={job.status === "cancelling"}>End generation</button>}
    </div>
    {workflowActive && stageSeconds >= 45 && <p className={`${ui.subtleNote} mb-5`} role="status">
      {job.kind === "dataset" && !job.result?.completed ? "No prompt has completed yet. " : "The current model request is still running. "}
      A local model may still be loading or generating. If the engine stops responding, its configured timeout will produce an error here; you can end generation now without waiting.
    </p>}

    {draft && <>
      <div className="grid grid-cols-[minmax(260px,0.8fr)_minmax(0,1.35fr)] items-start gap-[18px] mobile:grid-cols-1">
        <section className={ui.panel} aria-label="Dataset identity settings">
          <header className={ui.panelHeader}>
            <div className={ui.panelIcon}><Database size={21} /></div>
            <div className={ui.panelHeading}><h2>Dataset identity</h2><p>Define what must stay recognizable across every prompt.</p></div>
          </header>
          <fieldset disabled={disabled} className={ui.fields}>
            <label className={ui.field}><span>Trigger / prepend text</span>
              <input className={ui.input} aria-label="Trigger / prepend text" maxLength={200} value={draft.trigger}
                onChange={(event) => update({ trigger: event.target.value, quality_report: {} })} placeholder="e.g. ohwx_person" />
              <small className={ui.directorDescription}>Placed at the start of every result. For structured targets, it starts the primary description field.</small>
            </label>
            <label className={ui.field}><span>What is the trigger about?</span>
              <select className={ui.select} aria-label="What is the trigger about?" value={draft.trigger_type}
                onChange={(event) => updatePlanning({ trigger_type: event.target.value, coverage_axes: [] })}>
                {triggerTypes.map((item) => <option key={item}>{item}</option>)}
              </select>
            </label>
            {draft.trigger_type === "Custom" && <label className={ui.field}><span>Custom subject kind</span>
              <input className={ui.input} aria-label="Custom subject kind" maxLength={120} value={draft.custom_type}
                onChange={(event) => updatePlanning({ custom_type: event.target.value })} placeholder="e.g. architecture language, mascot, material" />
            </label>}
            <label className={ui.field}><span>Describe the consistent concept</span>
              <textarea className={ui.notesInput} aria-label="Describe the consistent concept" maxLength={10000}
                value={draft.subject} onChange={(event) => update({ subject: event.target.value, quality_report: {} })}
                placeholder="Describe identity, appearance, signature details, colors, materials, or style traits that every prompt must preserve." />
            </label>
            <label className={ui.field}><span>Consistency rules (optional)</span>
              <textarea className={ui.notesInput} aria-label="Consistency rules" maxLength={10000}
                value={draft.constraints} onChange={(event) => update({ constraints: event.target.value, quality_report: {} })}
                placeholder="Must keep the red jacket; no hats; preserve exact logo spelling…" />
            </label>
          </fieldset>
        </section>

        <section className={ui.panel} aria-label="Dataset generation settings">
          <header className={ui.panelHeader}>
            <div className={ui.panelIcon}><Sparkles size={21} /></div>
            <div className={ui.panelHeading}><h2>Coverage & direction</h2><p>Choose how the batch varies and where the prompts will be used.</p></div>
          </header>
          <fieldset disabled={disabled}>
            <div className="grid grid-cols-2 gap-4 tiny:grid-cols-1">
              <label className={ui.field}><span>Number of prompts</span>
                <select className={ui.select} aria-label="Number of prompts" value={draft.amount}
                  onChange={(event) => updatePlanning({ amount: Number(event.target.value) })}>
                  {Array.from({ length: 25 }, (_, index) => index + 1).map((amount) =>
                    <option key={amount} value={amount}>{amount}</option>)}
                </select>
              </label>
              <label className={ui.field}><span>Dataset variety</span>
                <select className={ui.select} aria-label="Dataset variety" value={draft.variety} onChange={(event) => updatePlanning({ variety: event.target.value, coverage_axes: [] })}>
                  {varieties.map((item) => <option key={item}>{item}</option>)}
                </select>
              </label>
              <label className={ui.field}><span>Visual style</span>
                <select className={ui.select} aria-label="Visual style" value={draft.visual_style} onChange={(event) => updatePlanning({ visual_style: event.target.value })}>
                  {visualStyles.map((item) => <option key={item}>{item}</option>)}
                </select>
              </label>
              <label className={ui.field}><span>Director preset</span>
                <select className={ui.select} aria-label="Dataset director preset" value={draft.director_preset} onChange={(event) => update({ director_preset: event.target.value })}>
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
              <TargetSelect label="Dataset target model" value={draft.target} targets={targets} disabled={disabled} onChange={(target) => update({ target, quality_report: {} })} />
              <label className={ui.field}><span>Prompt length</span>
                <select className={ui.select} aria-label="Dataset prompt length" value={draft.length} onChange={(event) => update({ length: event.target.value })}>
                  {lengths.map((item) => <option key={item}>{item}</option>)}
                </select>
              </label>
            </div>

            <fieldset className="mt-5 border-t border-line pt-4">
              <legend className="pr-2 text-xs font-semibold">Prompt sources</legend>
              <div className="mt-2 grid grid-cols-2 gap-2 tiny:grid-cols-1">
                {[['random', 'Concept-led variations', 'The model varies presentation inside your concept and consistency rules.'],
                  ['guided', 'Guided inputs', 'Use your one-line ideas as the scene direction.']].map(([value, label, help]) =>
                  <label key={value} className="cursor-pointer rounded-lg border border-line bg-[#11131b] p-3 has-checked:border-[#aa8cda] has-checked:bg-[#aa8cda12]">
                    <span className="flex items-center gap-2 text-xs font-semibold"><input type="radio" name="dataset-source" value={value}
                      checked={draft.source_mode === value} onChange={() => updatePlanning({ source_mode: value })} className="accent-[#aa8cda]" />{label}</span>
                    <small className="mt-2 block text-[10px] leading-relaxed text-muted">{help}</small>
                  </label>)}
              </div>
              {draft.source_mode === "guided" && <label className={`${ui.field} mt-4`}><span>Guided inputs · one per line ({guidedLines})</span>
                <textarea className={ui.ideaInput} style={{ minHeight: 160 }} aria-label="Guided dataset inputs" maxLength={50000}
                  value={draft.inputs} onChange={(event) => updatePlanning({ inputs: event.target.value })}
                  placeholder={"standing portrait in a city at night\nrunning through a sunlit field\nclose-up profile in a quiet studio"} />
                <small className={ui.directorDescription}>If you request more prompts than lines, inputs repeat with a new composition and treatment.</small>
              </label>}
            </fieldset>

            <section className="mt-5 border-t border-line pt-4" aria-label="Coverage planner">
              <details className="rounded-lg border border-line bg-[#11131b] p-3">
                <summary className="cursor-pointer text-xs font-semibold">Advanced coverage planning (optional)</summary>
                <p className="mt-3 text-[11px] leading-relaxed text-muted">Off by default. When off, your concept, romance or action rules, and guided inputs control the batch without automatic facet assignments.</p>
                <label className="mt-4 flex cursor-pointer items-start gap-3 rounded-lg border border-line bg-[#0d0f16] p-3 text-xs">
                  <input type="checkbox" className="mt-0.5 accent-[#aa8cda]" aria-label="Use coverage plan"
                    checked={coverageEnabled} onChange={(event) => update({ coverage_enabled: event.target.checked, quality_report: {} })} />
                  <span><strong className="block">Use coverage plan</strong>
                    <small className="mt-1 block leading-relaxed text-muted">Adds optional framing, viewpoint, lighting, and other category-specific cues. User instructions always take priority.</small></span>
                </label>
                {!coverageEnabled && draft.coverage_plan?.length > 0 && <p className={ui.subtleNote}>Your saved {draft.coverage_plan.length}-row plan is preserved but will be ignored.</p>}
                {coverageEnabled && <>
                  <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
                    <span className="text-[11px] font-medium">Optional coverage controls</span>
                    <div className="flex gap-2">
                      <button type="button" className={ui.button} disabled={plannerBusy || isGenerating}
                        onClick={() => createPlan(false)}><RefreshCw size={14} />{plannerBusy ? "Planning…" : "Create plan"}</button>
                      <button type="button" className={ui.button} disabled={plannerBusy || isGenerating || !draft.coverage_plan?.length}
                        onClick={() => createPlan(true)}><Shuffle size={14} />Shuffle</button>
                    </div>
                  </div>
                  <fieldset className="mt-4" disabled={disabled}>
                    <legend className="text-[11px] font-medium">Coverage axes</legend>
                    <div className="mt-2 flex flex-wrap gap-2">
                      {allowedAxes.map((key) => <label key={key}
                        className="flex cursor-pointer items-center gap-2 rounded-lg border border-line bg-[#0d0f16] px-3 py-2 text-[11px] has-checked:border-[#aa8cda] has-checked:text-[#d7c9ff]">
                        <input type="checkbox" className="accent-[#aa8cda]" aria-label={`Coverage axis ${axisLabels[key]}`}
                          checked={selectedAxes.includes(key)} onChange={(event) => {
                            const next = event.target.checked ? [...selectedAxes, key] : selectedAxes.filter((item) => item !== key);
                            if (next.length) updatePlanning({ coverage_axes: allowedAxes.filter((item) => next.includes(item)) });
                          }} />
                        {axisLabels[key]}
                      </label>)}
                    </div>
                  </fieldset>
                  {draft.coverage_plan?.length ? <div className="mt-4 overflow-x-auto rounded-lg border border-line">
                    <table className="w-full min-w-[720px] border-collapse text-left text-[10px]">
                      <thead className="bg-[#0d0f16] text-[#aaa7bd]"><tr>
                        <th className="px-3 py-2.5">#</th>
                        {draft.source_mode === "guided" && <th className="px-3 py-2.5">Guided input</th>}
                        {Object.keys(draft.coverage_plan[0]?.facets || {}).map((key) => <th key={key} className="px-3 py-2.5">{axisLabels[key] || key}</th>)}
                      </tr></thead>
                      <tbody>{draft.coverage_plan.map((row) => <tr key={row.index} className="border-t border-line text-[#c6c7d9]">
                        <td className="px-3 py-2.5 font-semibold text-[#b8a2f4]">{row.index}</td>
                        {draft.source_mode === "guided" && <td className="max-w-48 truncate px-3 py-2.5" title={row.input}>{row.input}</td>}
                        {Object.entries(row.facets).map(([key, value]) => <td key={key} className="px-3 py-2.5">{value}</td>)}
                      </tr>)}</tbody>
                    </table>
                  </div> : <p className={ui.subtleNote}>No plan yet. Create one to preview the optional assignments; generation can also create it automatically.</p>}
                </>}
              </details>
            </section>
            <button className={`${ui.primaryButton} mt-5 w-full`} disabled={!canGenerate} onClick={generate}>
              <Sparkles size={17} />{starting || isGenerating ? `Generating ${draft.amount} prompts…` : `Generate ${draft.amount} prompts`}
            </button>
          </fieldset>
        </section>
      </div>

      {!!draft.results.length && <section className={`${ui.panel} mt-6`} aria-label="Dataset quality report">
        <header className={ui.panelHeader}>
          <div className={ui.panelIcon}>{quality?.status === "strong" ? <ShieldCheck size={21} /> : <CircleAlert size={21} />}</div>
          <div className={ui.panelHeading}><h2>Dataset quality report</h2>
            <p>Automated diagnostics for trigger placement, formatting, uniqueness and leakage{coverageEnabled ? ", plus optional planned coverage" : ""}.</p></div>
          <span className={ui.resultStatus} data-working={qualityBusy || active && job?.kind === "dataset_review"}><span className={ui.statusDot} />
            {active && job?.kind === "dataset_review" ? "Reviewing" : qualityBusy ? "Checking" : quality?.status === "strong" ? "Strong" : quality?.status === "review" ? "Needs review" : quality?.status === "issues" ? "Issues found" : "Pending"}
          </span>
        </header>
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-line bg-[#11131b] px-3 py-2.5 text-[11px] text-muted">
          <span>{quality?.deep_review?.completed ? `Deep review complete · ${quality.deep_review.errors} errors · ${quality.deep_review.warnings} warnings` : "Optional: ask the prompt engine to check identity, style and constraint drift in bounded chunks."}</span>
          <button className={ui.button} disabled={disabled || noEngine || !draft.results.length} onClick={deepReview}>
            <ShieldCheck size={14} />{active && job?.kind === "dataset_review" ? "Deep reviewing…" : quality?.deep_review?.completed ? "Run deep review again" : "Deep consistency review"}
          </button>
        </div>
        {quality?.metrics ? <>
          <div className={`grid ${coverageEnabled ? "grid-cols-5" : "grid-cols-4"} gap-3 mobile:grid-cols-2`}>
            <div className="rounded-lg border border-line bg-[#11131b] p-3 mobile:col-span-2"><span className="text-[10px] text-muted">Overall</span><strong className="mt-1 block font-display text-xl text-[#d7c9ff]">{quality.score}</strong></div>
            {Object.entries(quality.metrics).map(([key, value]) => <div key={key} className="rounded-lg border border-line bg-[#11131b] p-3">
              <span className="text-[10px] capitalize text-muted">{key}</span><strong className="mt-1 block font-display text-xl">{value}%</strong>
            </div>)}
          </div>
          {!!quality.batch_issues?.length && <div className="mt-4 grid gap-2">
            {quality.batch_issues.map((issue, index) => <p key={`${issue.code}-${index}`} className={issue.severity === "error" ? ui.warningNote : ui.subtleNote}>
              <strong className="mr-1">{issue.severity === "error" ? "Issue:" : "Review:"}</strong>{issue.message}
            </p>)}
          </div>}
          <details className="mt-4 rounded-lg border border-line bg-[#11131b] p-3 text-xs">
            <summary className="cursor-pointer font-semibold">Prompt checks · {(quality.prompts || []).filter((item) => item.status === "pass").length}/{quality.prompts?.length || 0} passed</summary>
            <div className="mt-3 grid gap-2">{(quality.prompts || []).map((item) => <div key={item.index} className="flex items-start gap-2 border-t border-line pt-2 first:border-0 first:pt-0">
              {item.status === "pass" ? <CircleCheck size={15} className="text-success" /> : <CircleAlert size={15} className={item.status === "error" ? "text-[#e8a2a2]" : "text-[#d5b879]"} />}
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
        {!draft.results.length ? <div className={`${ui.emptyState} min-h-[260px]`}>
          <Database size={34} /><h3>Your batch will appear here.</h3><p>Define the trigger and direction above, then generate up to 25 distinct prompts.</p>
        </div> : <div className="grid grid-cols-2 gap-4 [@media(width<=1050px)]:grid-cols-1">
          {draft.results.map((item) => {
            const check = promptQuality.get(item.index);
            return <article className={ui.panel} key={item.index}>
            <div className="mb-3 flex items-center justify-between gap-3">
              <div><span className="text-[10px] font-semibold tracking-[1.3px] text-[#b8a2f4]">PROMPT {item.index}</span>
                {item.input && <p className="mt-1 max-w-[48ch] truncate text-[10px] text-muted" title={item.input}>{item.input}</p>}
                {check && <span className={`mt-1 inline-flex items-center gap-1 text-[9px] ${check.status === "pass" ? "text-success" : check.status === "error" ? "text-[#e8a2a2]" : "text-[#d5b879]"}`}>
                  {check.status === "pass" ? <CircleCheck size={11} /> : <CircleAlert size={11} />}{check.status === "pass" ? "Passed checks" : `${check.issues.length} ${check.issues.length === 1 ? "issue" : "issues"}`}
                </span>}</div>
              <button className={ui.button} onClick={() => onCopy(item.prompt)}><Copy size={14} />Copy</button>
            </div>
            <textarea className={ui.outputInput} style={{ minHeight: 220 }} aria-label={`Dataset prompt ${item.index}`}
              value={item.prompt} maxLength={100000} disabled={isGenerating || active && job?.kind === "dataset_review"}
              onChange={(event) => editResult(item.index, event.target.value)} />
          </article>})}
        </div>}
      </section>
    </>}
  </div>;
}
