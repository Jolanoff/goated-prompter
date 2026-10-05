import { useEffect, useRef, useState } from "react";
import { api } from "../api.js";
import { datasetRetryStage, invalidateDatasetPrompts, isDatasetSceneCurrent } from "./datasetState.js";

/** Dataset requests and job projections; editable-draft revisions stay in useWorkflowSettings. */
export function useDatasetWorkflow({ preferences, job, busy, active, noEngine, director,
  onGenerate, onReleaseJobs }) {
  const { draft, update, refreshGenerated } = preferences;
  const [starting, setStarting] = useState(false);
  const [qualityBusy, setQualityBusy] = useState(false);
  const [error, setError] = useState("");
  const [resettingIdeas, setResettingIdeas] = useState(false);
  const [noveltyNotice, setNoveltyNotice] = useState("");
  const submission = useRef(false);
  const synced = useRef("");
  const qualityAttempt = useRef(0);
  const datasetJob = ["dataset", "dataset_scenes", "dataset_review"].includes(job?.kind);
  const workflowActive = datasetJob && active;
  const disabled = busy || starting || preferences.working;
  const guidedLines = draft?.inputs.split("\n").filter((line) => line.trim()).length || 0;
  const customReady = draft?.trigger_type !== "Custom" || draft.custom_type.trim();
  const styleReady = draft?.visual_style !== "Custom" || draft.custom_style.trim();
  const sourceReady = draft?.source_mode !== "guided" || guidedLines > 0;
  const canPlanScenes = draft && !disabled && !noEngine && !preferences.conflict &&
    draft.subject.trim() && customReady && styleReady && sourceReady;
  const staleScenePlan = !!draft?.scene_plan_signature &&
    (preferences.record?.scene_plan_matches_settings ?? preferences.record?.idea_plan_current) === false &&
    preferences.record?.draft.scene_plan_signature === draft.scene_plan_signature;
  const sceneUsable = (row) => isDatasetSceneCurrent(
    draft?.scene_plan?.find((item) => item.index === row.index), preferences.record,
  );
  const validSceneCount = draft?.scene_plan?.filter(sceneUsable).length || 0;
  const retryStage = (row) => datasetRetryStage(row, { usable: sceneUsable(row) });
  const scenePlanReady = !staleScenePlan && !!draft?.scene_plan_signature && validSceneCount > 0;
  const canWrite = canPlanScenes && director && draft.trigger.trim();
  const canGenerate = canWrite && !draft.scene_plan?.some((item) =>
    item.scene_status !== "failed" && item.idea !== undefined && !item.idea.trim());

  useEffect(() => {
    if (!datasetJob || !["failed", "interrupted"].includes(job.status)) return;
    setError(`${job.kind === "dataset_review" ? "Dataset review" : job.kind === "dataset_scenes" ? "Scene planning" : "Dataset generation"} failed. ${job.error || "The prompt engine did not return a usable result."}`);
  }, [datasetJob, job?.id, job?.revision, job?.status, job?.kind, job?.error]);

  useEffect(() => {
    if (!draft || !["dataset", "dataset_scenes"].includes(job?.kind) || !job.result?.scene_plan) return;
    const key = `${job.id}:${job.revision}`;
    if (synced.current === key) return;
    synced.current = key;
    refreshGenerated().catch((err) => setError(`Could not recover saved progress. ${err.message}`));
  }, [job, draft, refreshGenerated]);

  useEffect(() => {
    if (!draft || job?.kind !== "dataset_review" || job.status !== "succeeded" || !job.result?.report) return;
    const key = `review:${job.id}:${job.revision}`;
    if (synced.current === key) return;
    synced.current = key;
    refreshGenerated().catch((err) => setError(err.message));
  }, [job, draft, refreshGenerated]);

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
      await onGenerate("dataset/scene", { input: draft, index, action, workflow_revision: preferences.revision() });
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
      await onGenerate(scenesOnly ? "dataset/scenes" : "dataset", { input,
        workflow_revision: preferences.revision(), ...(validOnly ? { valid_only: true } : {}) });
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
      await onGenerate("dataset/review", { input: draft, workflow_revision: preferences.revision() });
    } catch (err) { setError(err.message); }
    finally { submission.current = false; setStarting(false); }
  }

  function editResult(index, prompt) {
    update({ results: draft.results.map((item) => item.index === index ? { ...item, prompt } : item), quality_report: {} });
  }

  async function releaseCheckpoints() {
    try {
      await preferences.flush();
      await onReleaseJobs?.("dataset");
    } catch (err) { setError(`Could not release temporary job checkpoints. ${err.message}`); }
  }

  async function clearResults() {
    update({ results: [], result_job_id: "", quality_report: {} });
    await releaseCheckpoints();
  }

  async function resetRecentIdeas() {
    setResettingIdeas(true);
    setNoveltyNotice("");
    try {
      await api("/workspace/dataset/novelty/reset", { input: draft });
      setNoveltyNotice("Recent ideas reset for this concept. Current scenes and prompts are unchanged.");
    } catch (err) { setError(err.message); }
    finally { setResettingIdeas(false); }
  }

  return { starting, qualityBusy, error, resettingIdeas, noveltyNotice, workflowActive, disabled,
    guidedLines, canPlanScenes, staleScenePlan, sceneUsable, validSceneCount, retryStage,
    scenePlanReady, canWrite, canGenerate, updateSceneSettings, updateWriterSettings,
    sceneAction, generate, deepReview, editResult, releaseCheckpoints, clearResults, resetRecentIdeas };
}
