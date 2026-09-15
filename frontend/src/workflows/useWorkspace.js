import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api.js";

/** Server-backed workspace state; mutations use optimistic revision checks. */
export function useWorkspace(job, onReceiveJob) {
  const [snapshot, setSnapshot] = useState(null);
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  const writing = useRef(false);
  const latest = useRef(null);
  const mounted = useRef(true);
  const accept = useCallback((next) => {
    if (!mounted.current || (latest.current && latest.current.revision > next.revision)) return;
    latest.current = next;
    setSnapshot(next);
  }, []);
  const refresh = useCallback(async () => {
    try {
      const next = await api("/workspace");
      accept(next);
      return next;
    } catch (err) {
      if (mounted.current) setError(`Could not load version history. ${err.message}`);
      return null;
    }
  }, [accept]);
  useEffect(() => {
    mounted.current = true;
    refresh();
    return () => { mounted.current = false; };
  }, [refresh]);
  useEffect(() => {
    if (job?.id) refresh();
  }, [job?.id, job?.revision, refresh]);

  async function mutate(payload) {
    if (writing.current || !latest.current) return null;
    writing.current = true;
    setPending(true);
    setError("");
    try {
      const next = await api("/workspace", { ...payload, revision: latest.current.revision });
      accept(next);
      return next;
    } catch (err) {
      if (err.activeJob) onReceiveJob(err.activeJob);
      if (err.status === 409) await refresh();
      setError(err.message);
      return null;
    } finally {
      writing.current = false;
      setPending(false);
    }
  }
  return { snapshot, error, setError, pending, mutate, refresh };
}
