import { useEffect, useRef, useState } from "react";
import { api } from "../api.js";
import { datasetRequestSignature, reviseDatasetRequest } from "./datasetState.js";

export function useDatasetConfirmation({ draft, job, busy, onGenerate, onConfirm, setError }) {
  const [confirmation, setConfirmation] = useState(null);
  const pending = useRef(null);
  const opener = useRef(null);
  const latestDraft = useRef(draft);
  latestDraft.current = draft;

  async function analyze(item) {
    pending.current = item;
    setConfirmation({ ...item, status: "analyzing", brief: null, confirmation_token: "", error: "" });
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
      setConfirmation((current) => current && { ...current, ...job.result, status: "ready" });
    } else if (["failed", "cancelled", "interrupted"].includes(job.status)) {
      setConfirmation((current) => current && { ...current, status: "failed",
        error: job.error || "Request analysis stopped. No ideas, scenes or prompts were generated." });
    }
  }, [confirmation?.jobId, confirmation?.status, job]);

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

  function requestConfirmation(operation, options = {}) {
    if (pending.current) return;
    // The review lock disables the launcher before showModal can remember it.
    opener.current = document.activeElement;
    setError("");
    void analyze({ input: draft, operation, options, baseSignature: datasetRequestSignature(draft) });
  }

  function cancelConfirmation() {
    const item = pending.current;
    pending.current = null;
    setConfirmation(null);
    if (item?.jobId && job?.id === item.jobId && !["succeeded", "failed", "cancelled", "interrupted"].includes(job.status)) {
      void api(`/jobs/${item.jobId}/cancel`, {}).catch((err) => setError(err.message));
    }
  }

  function reviseConfirmation(additions) {
    if (!confirmation || busy || ["analyzing", "confirming"].includes(confirmation.status)) return;
    const input = reviseDatasetRequest(confirmation.input, additions);
    const needsReplan = input !== confirmation.input;
    void analyze({ input, baseSignature: confirmation.baseSignature,
      operation: needsReplan && confirmation.operation === "dataset/scene" ? "dataset" : confirmation.operation,
      options: needsReplan ? {} : confirmation.options,
      notice: needsReplan ? "New rules require fresh ideas and scenes for this batch." : confirmation.notice });
  }

  async function confirmRequest() {
    if (!confirmation?.confirmation_token || confirmation.status !== "ready" || busy || confirmation.brief?.blocking_questions?.length) return;
    if (datasetRequestSignature(latestDraft.current) !== confirmation.baseSignature) {
      setConfirmation((current) => current && { ...current, confirmation_token: "",
        error: "Dataset settings changed during review. Cancel and review the updated request." });
      return;
    }
    const item = confirmation;
    setConfirmation({ ...item, status: "confirming", error: "" });
    try {
      const accepted = await onConfirm(item);
      if (!accepted) throw new Error("Generation did not start. Your previous batch is unchanged; try again.");
      pending.current = null;
      setConfirmation(null);
    } catch (err) {
      setConfirmation({ ...item, status: "ready", error: err.message });
    }
  }

  return { confirmation, requestConfirmation, reviseConfirmation, cancelConfirmation, confirmRequest };
}
