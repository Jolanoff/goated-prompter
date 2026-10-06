import { useEffect, useRef, useState } from "react";
import { api } from "../api.js";
import { datasetRetryStage, invalidateDatasetPrompts, isDatasetSceneCurrent } from "./datasetState.js";
import { useDatasetConfirmation } from "./useDatasetConfirmation.js";

/** Dataset requests and job projections; editable-draft revisions stay in useWorkflowSettings. */
export function useDatasetWorkflow({ preferences, job, busy, active, noEngine, director,
  onGenerate, onReleaseJobs }) {
  const { draft, update, refreshGenerated } = preferences;
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState("");
  const [resettingIdeas, setResettingIdeas] = useState(false);
  const [noveltyNotice, setNoveltyNotice] = useState("");
  const submission = useRef(false);
  const synced = useRef("");
  const confirmationFlow = useDatasetConfirmation({ draft, job, busy, onGenerate,
    onConfirm: admitConfirmed, setError });
  const datasetJob = ["dataset", "dataset_scenes", "dataset_understanding"].includes(job?.kind);
  const workflowActive = datasetJob && active;
  const disabled = busy || starting || preferences.working || !!confirmationFlow.confirmation;
  const guidedLines = draft?.inputs.split("\n").filter((line) => line.trim()).length || 0;
  const customReady = draft?.trigger_type !== "Custom" || draft.custom_type.trim();
  const styleReady = draft?.visual_style !== "Custom" || draft.custom_style.trim();
  const sourceReady = draft?.source_mode !== "guided" || guidedLines > 0;
  const canPlanScenes = draft && !disabled && !noEngine && !preferences.conflict &&
    draft.subject.trim() && customReady && styleReady && sourceReady;
  const staleScenePlan = !!draft?.scene_plan_signature &&
    preferences.record?.scene_plan_matches_settings === false &&
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
    setError(`${job.kind === "dataset_understanding" ? "Request analysis" : job.kind === "dataset_scenes" ? "Scene planning" : "Dataset generation"} failed. ${job.error || "The prompt engine did not return a usable result."}`);
  }, [datasetJob, job?.id, job?.revision, job?.status, job?.kind, job?.error]);

  useEffect(() => {
    if (!draft || !["dataset", "dataset_scenes"].includes(job?.kind) || !job.result?.scene_plan) return;
    const key = `${job.id}:${job.revision}`;
    if (synced.current === key) return;
    synced.current = key;
    refreshGenerated().catch((err) => setError(`Could not recover saved progress. ${err.message}`));
  }, [job, draft, refreshGenerated]);

  function updateSceneSettings(patch) {
    update({ ...patch, scene_plan: [], scene_plan_signature: "", results: [] });
  }

  function updateWriterSettings(patch) {
    update(invalidateDatasetPrompts(draft, patch));
  }

  function sceneAction(index, action) {
    if (disabled || staleScenePlan || !canWrite || submission.current) return;
    confirmationFlow.requestConfirmation("dataset/scene", { index, action });
  }

  async function admitConfirmed(review) {
    if (busy || preferences.working || preferences.conflict || noEngine || submission.current) return false;
    submission.current = true;
    setStarting(true);
    setError("");
    try {
      await preferences.flush();
      return await onGenerate(review.operation, { input: { ...review.input, results: draft.results,
        result_job_id: draft.result_job_id }, ...review.options,
        confirmation_token: review.confirmation_token, workflow_revision: preferences.revision() });
    }
    finally { submission.current = false; setStarting(false); }
  }

  function generate(scenesOnly = false, validOnly = false) {
    if (!(scenesOnly ? canPlanScenes : validOnly ? canWrite && scenePlanReady : canGenerate) || submission.current) return;
    confirmationFlow.requestConfirmation(scenesOnly ? "dataset/scenes" : "dataset", validOnly ? { valid_only: true } : {});
  }

  function editResult(index, prompt) {
    if (disabled) return;
    update({ results: draft.results.map((item) => item.index === index ? { ...item, prompt } : item) });
  }

  async function releaseCheckpoints() {
    try {
      await preferences.flush();
      await onReleaseJobs?.("dataset");
    } catch (err) { setError(`Could not release temporary job checkpoints. ${err.message}`); }
  }

  async function clearResults() {
    update({ results: [], result_job_id: "" });
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

  return { starting, error, resettingIdeas, noveltyNotice, workflowActive, disabled,
    ...confirmationFlow,
    guidedLines, canPlanScenes, staleScenePlan, sceneUsable, validSceneCount, retryStage,
    scenePlanReady, canWrite, canGenerate, updateSceneSettings, updateWriterSettings,
    sceneAction, generate, editResult, releaseCheckpoints, clearResults, resetRecentIdeas };
}
