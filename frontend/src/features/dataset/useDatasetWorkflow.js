import { useEffect, useState } from "react";
import { datasetConfirmationPayload, nextDatasetSeed } from "./datasetState.js";
import { useDatasetConfirmation } from "./useDatasetConfirmation.js";

/** Dataset requests and job projections; editable-draft revisions stay in useWorkflowSettings. */
export function useDatasetWorkflow({ preferences, job, busy, active, noEngine, director,
  onGenerate, vocabularyPacks = [], packsReady = true, visualDirection = null }) {
  const { draft, update } = preferences;
  const [error, setError] = useState("");
  const confirmationFlow = useDatasetConfirmation({ draft, job, busy, onGenerate,
    onConfirm: async (item) => {
      const accepted = await onGenerate("dataset/v2/confirm", datasetConfirmationPayload(item));
      if (accepted) update({ seed: item.input.seed });
      return accepted;
    }, setError, vocabularyPacks, visualDirection });
  const datasetJob = ["dataset_understanding", "dataset_v2_scenes"].includes(job?.kind);
  const workflowActive = datasetJob && active;
  const disabled = busy || preferences.working || !!confirmationFlow.confirmation;
  const guidedLines = draft?.inputs.split("\n").filter((line) => line.trim()).length || 0;
  const sourceReady = draft?.source_mode !== "guided" || guidedLines > 0;
  const canPlanScenes = draft && !disabled && !noEngine && !preferences.conflict &&
    draft.subject.trim() && sourceReady;
  const canWrite = canPlanScenes && director;

  useEffect(() => {
    if (!datasetJob || !["failed", "interrupted"].includes(job.status)) return;
    setError(`${job.kind === "dataset_understanding" ? "Request analysis" : "Dataset generation"} failed. ${job.error || "The prompt engine did not return a usable result."}`);
  }, [datasetJob, job?.id, job?.revision, job?.status, job?.kind, job?.error]);

  // Each batch is reviewed first; Confirm then writes scenes, and prompts unless scenes only was chosen.
  function generateDataset() {
    if (!canWrite || !packsReady) return;
    confirmationFlow.requestConfirmation("dataset", {}, { ...draft, seed: nextDatasetSeed(draft) });
  }

  function generateScenes() {
    if (!canPlanScenes || !packsReady) return;
    confirmationFlow.requestConfirmation("dataset/scenes", {}, { ...draft, seed: nextDatasetSeed(draft) });
  }

  return { error, workflowActive, disabled, ...confirmationFlow,
    guidedLines, canPlanScenes, canWrite, generateDataset, generateScenes };
}
