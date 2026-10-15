import { useEffect, useRef, useState } from "react";
import { api } from "../../api.js";
import { canConfirmDatasetReview, datasetRequestSignature, reviseDatasetRequest } from "./datasetState.js";

export function useDatasetConfirmation({ draft, job, busy, onGenerate, onConfirm, setError, vocabularyPacks = [] }) {
  const [confirmation, setConfirmation] = useState(null);
  const [understanding, setUnderstanding] = useState(null);
  // Rebuild (issue 106): the run started by Confirm; the tab's Scenes and Dataset pages show it.
  const [run, setRun] = useState(null);
  const pending = useRef(null);
  const opener = useRef(null);
  const latestDraft = useRef(draft);
  latestDraft.current = draft;
  // The pack choice is frozen into each review when it starts and sent with Confirm (Phase 2).
  const latestPacks = useRef(vocabularyPacks);
  latestPacks.current = vocabularyPacks;

  async function analyze(item) {
    pending.current = item;
    setUnderstanding(null);
    setConfirmation({ ...item, status: "analyzing", brief: null, summary: null, confirmation_token: "", error: "" });
    try {
      const accepted = await onGenerate("dataset/understand", { input: item.input });
      if (!accepted) throw new Error("Request analysis could not start. Wait for active work and try again.");
      item.jobId = accepted.id;
      if (pending.current !== item) {
        await api(`/jobs/${accepted.id}/cancel`, {});
        return;
      }
      setConfirmation((current) => current && { ...current, jobId: accepted.id });
    } catch (err) {
      if (pending.current === item) setConfirmation((current) => current && { ...current, status: "failed", error: err.message });
    }
  }

  useEffect(() => {
    if (!confirmation?.jobId || job?.id !== confirmation.jobId || confirmation.status !== "analyzing") return;
    if (job.status === "succeeded") {
      const reviewed = { ...confirmation, ...job.result, status: "ready" };
      setConfirmation(reviewed);
      setUnderstanding(reviewed);
    } else if (["failed", "cancelled", "interrupted"].includes(job.status)) {
      setConfirmation((current) => current && { ...current, status: "failed",
        error: job.error || "Request analysis stopped. No ideas, scenes or prompts were generated." });
    }
  }, [confirmation, job]);

  // Follow the run's job: scenes arrive first, then each final prompt.
  useEffect(() => {
    if (!run?.jobId || job?.id !== run.jobId) return;
    const result = job.result?.kind === "dataset_v2_scenes" ? job.result : run.result;
    const status = job.status === "succeeded" ? "done"
      : ["failed", "cancelled", "interrupted"].includes(job.status) ? "failed" : "running";
    if (result === run.result && status === run.status) return;
    setRun((current) => current?.jobId === job.id ? { ...current, result, status,
      error: status === "failed" ? job.error || "This run stopped. See the console and the debug files." : "" } : current);
  }, [job, run]);

  useEffect(() => () => { pending.current = null; }, []);

  useEffect(() => {
    if (confirmation || busy || !opener.current) return;
    const element = opener.current;
    const frame = requestAnimationFrame(() => {
      if (element.isConnected && !element.matches(":disabled")) element.focus();
      opener.current = null;
    });
    return () => cancelAnimationFrame(frame);
  }, [confirmation, busy]);

  function requestConfirmation(operation, options = {}, input = draft) {
    if (pending.current) return;
    // The review lock disables the launcher before showModal can remember it.
    opener.current = document.activeElement;
    setError("");
    void analyze({ input, operation, options, baseSignature: datasetRequestSignature(draft), vocabulary_packs: [...latestPacks.current] });
  }

  function cancelConfirmation() {
    const item = pending.current;
    pending.current = null;
    if (confirmation) setUnderstanding({ ...confirmation, status: "cancelled" });
    setConfirmation(null);
    if (item?.jobId && job?.id === item.jobId && !["succeeded", "failed", "cancelled", "interrupted"].includes(job.status)) {
      void api(`/jobs/${item.jobId}/cancel`, {}).catch((err) => setError(err.message));
    }
  }

  function reviseConfirmation(additions) {
    if (!confirmation || busy || ["analyzing", "confirming"].includes(confirmation.status)) return;
    const input = reviseDatasetRequest(confirmation.input, additions);
    const needsReplan = input !== confirmation.input;
    void analyze({ input, baseSignature: confirmation.baseSignature, vocabulary_packs: confirmation.vocabulary_packs,
      operation: confirmation.operation === "dataset/scenes" ? "dataset/scenes" : needsReplan ? "dataset" : confirmation.operation,
      options: needsReplan ? {} : confirmation.options,
      notice: needsReplan ? "Understanding will use your corrections. Fresh scenes will be planned after confirmation." : confirmation.notice });
  }

  async function confirmRequest() {
    if (!canConfirmDatasetReview(confirmation, busy)) return;
    if (datasetRequestSignature(latestDraft.current) !== confirmation.baseSignature) {
      setConfirmation((current) => current && { ...current, confirmation_token: "",
        error: "Dataset settings changed during review. Cancel and review the updated request." });
      return;
    }
    const item = confirmation;
    setConfirmation({ ...item, status: "confirming", error: "" });
    try {
      const accepted = await onConfirm(item);
      if (!accepted) throw new Error("Scene writing could not start. Wait for active work and try again.");
      pending.current = null;
      setUnderstanding({ ...item, status: "confirmed" });
      setConfirmation(null);
      setRun({ jobId: accepted.id, brief: item.brief, vocabulary_packs: item.vocabulary_packs, status: "running", result: null, error: "" });
    } catch (err) {
      setConfirmation({ ...item, status: "ready", error: err.message });
    }
  }

  // Understanding v10: corrections to the structured details travel with Confirm; the server checks them again.
  function editIntent(intent) {
    setConfirmation((current) => current?.status === "ready" && current.brief?.intent
      ? { ...current, brief: { ...current.brief, intent }, error: "" } : current);
  }

  return { confirmation, understanding: confirmation || understanding, run,
    requestConfirmation, reviseConfirmation, cancelConfirmation, confirmRequest, editIntent };
}
