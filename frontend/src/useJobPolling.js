import { useEffect, useEffectEvent } from "react";
import { api } from "./api.js";

export const activeJobStatuses = ["running", "pause_requested", "paused", "cancelling"];

/** A single non-overlapping poll stream; abort requests when the job changes. */
export function useJobPolling(jobID, active, onJob, onMissing, onError) {
  const receive = useEffectEvent(onJob);
  const missing = useEffectEvent(onMissing);
  const failed = useEffectEvent(onError);
  useEffect(() => {
    if (!active || !jobID) return;
    const controller = new AbortController();
    let timer;
    async function poll() {
      try {
        const next = await api(`/jobs/${jobID}`, undefined, "GET", { signal: controller.signal });
        if (controller.signal.aborted) return;
        receive(next);
        if (!activeJobStatuses.includes(next.status)) return;
      } catch (error) {
        if (controller.signal.aborted) return;
        if (error.status === 404) { missing(); return; }
        failed(error);
      }
      if (!controller.signal.aborted) timer = setTimeout(poll, 700);
    }
    poll();
    return () => { controller.abort(); clearTimeout(timer); };
    // Effect events read current callbacks without restarting active requests.
  }, [jobID, active]);
}
