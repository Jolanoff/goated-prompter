import { useEffect, useEffectEvent, useRef, useState } from "react";
import { api } from "../../api.js";

export function useDatasetConfirmation({ draft, job, busy, onGenerate, onConfirm, setError }) {
  const [confirmation, setConfirmation] = useState(null);
  const [understanding, setUnderstanding] = useState(null);
  // Rebuild (issue 106): the run started once Understanding succeeds; the tab's Scenes and Dataset pages show it.
  const [run, setRun] = useState(null);
  const pending = useRef(null);
  const opener = useRef(null);

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

  const continueToRun = useEffectEvent((understood) => { void startRun(understood); });

  useEffect(() => {
    if (!confirmation?.jobId || job?.id !== confirmation.jobId || confirmation.status !== "analyzing") return;
    if (job.status === "succeeded") {
      // No review step: the understood request goes straight on to scene writing.
      const understood = { ...confirmation, ...job.result, status: "confirming" };
      setConfirmation(understood);
      setUnderstanding(understood);
      continueToRun(understood);
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
      error: status === "failed" ? job.error || "This run stopped before it finished." : "" } : current);
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
    // The overlay lock disables the launcher before showModal can remember it.
    opener.current = document.activeElement;
    setError("");
    void analyze({ input, operation, options });
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

  async function startRun(understood) {
    const item = pending.current;
    try {
      const accepted = await onConfirm(understood);
      if (!accepted) throw new Error("Scene writing could not start. Wait for active work and try again.");
      if (pending.current !== item) {
        // Cancelled while the run was starting.
        await api(`/jobs/${accepted.id}/cancel`, {});
        return;
      }
      pending.current = null;
      setUnderstanding({ ...understood, status: "confirmed" });
      setConfirmation(null);
      setRun({ jobId: accepted.id, brief: understood.brief, vocabulary: [...(understood.input.vocabulary_packs || [])], status: "running", result: null, error: "" });
    } catch (err) {
      if (pending.current === item) setConfirmation((current) => current && { ...current, status: "failed", error: err.message });
    }
  }

  return { confirmation, understanding: confirmation || understanding, run,
    requestConfirmation, cancelConfirmation };
}
