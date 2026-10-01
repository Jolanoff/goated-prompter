import { useEffect, useRef, useState } from "react";
import { Check, Copy, ScrollText, X } from "lucide-react";
import { ui } from "./ui.js";

function timestamp(value) {
  if (!Number.isFinite(value)) return "--:--:--";
  return new Date(value * 1000).toLocaleTimeString([], {
    hour: "2-digit", minute: "2-digit", second: "2-digit",
  });
}

function elapsed(started, now) {
  if (!Number.isFinite(started)) return "";
  const seconds = Math.max(0, Math.floor(now / 1000 - started));
  return seconds >= 60 ? `${Math.floor(seconds / 60)}m ${seconds % 60}s` : `${seconds}s`;
}

function messageText(content) {
  if (typeof content === "string") return content;
  if (!Array.isArray(content)) return JSON.stringify(content ?? "", null, 2);
  return content.map((part) => {
    if (part?.type === "text") return part.text || "";
    if (part?.type === "image_url") {
      const image = part.image_url || {};
      return `[IMAGE: ${image.media || image.source || "attached image"}; sha256=${image.sha256 || "unavailable"}]`;
    }
    return JSON.stringify(part, null, 2);
  }).join("\n\n");
}

function explanation(job, now) {
  if (!job) return "No generation job is available.";
  if (job.status === "pause_requested") {
    return "A pause was requested. Live response text may continue to appear, but the active model call must end before the workflow can pause at its next safe checkpoint.";
  }
  if (job.status === "paused") {
    return "The job is paused at a safe checkpoint. The model is not being asked for another response until the job is resumed.";
  }
  if (job.status === "cancelling") {
    return "Cancellation is in progress. A managed local engine is being interrupted; other engines may need to return before the worker can stop safely.";
  }
  if (job.llm_trace?.status === "waiting_first_token") {
    const timeout = Number(job.llm_trace.timeout_seconds);
    const limit = Number.isFinite(timeout) ? ` The request timeout is ${timeout} seconds.` : "";
    return `The exact request below was sent ${elapsed(job.llm_trace.started_at, now)} ago. The engine has not returned its first text yet; it may be loading, evaluating the input, queued, or stalled.${limit}`;
  }
  if (job.llm_trace?.status === "receiving") {
    return `The engine is returning text now. The live response below was last updated at ${timestamp(job.llm_trace.updated_at)}.`;
  }
  if (job.llm_trace?.status === "error") return job.llm_trace.issue;
  if (job.status === "running" && String(job.progress || "").includes("Waiting for prompt engine")) {
    return "The workflow is waiting for the model, but this request has not exposed live transport data. The next visible event will be a response, timeout, or cancellation.";
  }
  return job.status_reason || job.progress || "Waiting for the next runtime update.";
}

function fallbackEvents(job) {
  if (!job) return [];
  const events = [{ id: "created", timestamp: job.created_at, type: "status", message: "Job accepted." }];
  if (job.progress) events.push({ id: "progress", timestamp: job.progress_at, type: "stage", message: job.progress });
  if (job.error) events.push({ id: "error", timestamp: job.finished_at, type: "error", message: job.error });
  return events;
}

export default function JobLogModal({ open, job, engineLabel, onClose }) {
  const dialog = useRef(null);
  const [copied, setCopied] = useState(false);
  const [clock, setClock] = useState(Date.now());
  const events = job?.events?.length ? job.events : fallbackEvents(job);
  const trace = job?.llm_trace;

  useEffect(() => {
    if (open && job && !dialog.current?.open) dialog.current?.showModal();
    else if ((!open || !job) && dialog.current?.open) dialog.current.close();
  }, [open, job]);

  useEffect(() => {
    if (!open || !["waiting_first_token", "receiving"].includes(trace?.status)) return;
    setClock(Date.now());
    const timer = setInterval(() => setClock(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [open, trace?.status, trace?.request_number]);

  async function copyLog() {
    const request = (trace?.messages || []).map((message) =>
      `${String(message.role || "message").toUpperCase()}\n${messageText(message.content)}`).join("\n\n");
    const lines = [
      `STATUS: ${job?.status || "unknown"}`,
      `CURRENT ACTIVITY: ${explanation(job, clock)}`,
      trace ? `\nREQUEST ${trace.request_number}\nMODEL: ${trace.model}\n${request}` : "",
      trace?.reasoning ? `\nENGINE-EXPOSED REASONING\n${trace.reasoning}` : "",
      trace ? `\nLIVE OUTPUT\n${trace.output || "[No response text received]"}` : "",
      "\nEVENTS",
      ...events.map((event) => `[${timestamp(event.timestamp)}] ${event.type.toUpperCase()}: ${event.message}`),
    ];
    try {
      await navigator.clipboard.writeText(lines.join("\n"));
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      setCopied(false);
    }
  }

  return <dialog ref={dialog}
    className="app-dialog log-dialog"
    aria-labelledby="llm-log-title" onCancel={(event) => { event.preventDefault(); onClose(); }} onClose={onClose}>
    <header className="flex items-start gap-4 border-b border-line px-6 py-5 mobile:px-4">
      <div className={ui.panelIcon}><ScrollText size={21} /></div>
      <div className="min-w-0 flex-1">
        <h2 id="llm-log-title" className="font-display text-xl font-bold">LLM activity log</h2>
        <p className="mt-1 text-xs leading-relaxed text-muted">Requests, live responses, and validation events. Reasoning is shown only when returned by the engine.</p>
      </div>
      <button className={ui.iconButton} onClick={onClose} aria-label="Close LLM activity log"><X size={18} /></button>
    </header>
    <div className="max-h-[72dvh] overflow-y-auto px-6 py-5 mobile:px-4">
      <div className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 rounded-lg border border-line bg-canvas p-4 text-xs mobile:grid-cols-1">
        <strong>Status</strong><span className="capitalize text-accent">{job?.status?.replaceAll("_", " ") || "Unavailable"}</span>
        <strong>Workflow</strong><span className="capitalize text-muted">{job?.kind?.replaceAll("_", " ") || "Unknown"}</span>
        <strong>Engine</strong><span className="text-muted">{engineLabel || "Unknown"}</span>
        {trace?.timeout_seconds && <><strong>Request timeout</strong><span className="text-muted">{trace.timeout_seconds} seconds</span></>}
        <strong>Current activity</strong><span className="leading-relaxed text-muted">{explanation(job, clock)}</span>
        <strong>Job</strong><span className="truncate font-code text-xs text-muted" title={job?.id}>{job?.id || "None"}</span>
      </div>
      {trace && <section className="mt-4" aria-label="Current LLM request">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="text-xs font-semibold">Current LLM request · {trace.request_number}</h3>
          <span className="rounded border border-line bg-selected px-2 py-1 text-xs text-accent">{trace.status.replaceAll("_", " ")}</span>
        </div>
        <details className="mt-3 rounded-lg border border-line bg-canvas p-3" open={trace.status === "waiting_first_token"}>
          <summary className="cursor-pointer text-xs font-semibold">What the model is reading</summary>
          <div className="mt-3 grid gap-3">
            {(trace.messages || []).map((message, index) => <article key={`${message.role}-${index}`} className="rounded border border-line bg-surface p-3">
              <strong className="text-xs capitalize text-accent">{message.role || "message"}</strong>
              <pre tabIndex={0} role="region" aria-label={`Request message ${index + 1}: ${message.role || "message"}`}
                className="mt-2 max-h-[280px] overflow-auto whitespace-pre-wrap wrap-anywhere font-code text-xs leading-relaxed text-ink">{messageText(message.content)}</pre>
            </article>)}
            <details className="text-xs text-muted"><summary className="cursor-pointer">Request parameters</summary>
              <pre className="mt-2 whitespace-pre-wrap wrap-anywhere font-code">{JSON.stringify(trace.parameters || {}, null, 2)}</pre>
            </details>
          </div>
        </details>
        {!!trace.reasoning && <details className="mt-3 rounded-lg border border-line bg-canvas p-3">
          <summary className="cursor-pointer text-xs font-semibold">Reasoning text explicitly returned by the engine</summary>
          <pre tabIndex={0} role="region" aria-label="Engine reasoning"
            className="mt-3 max-h-[240px] overflow-auto whitespace-pre-wrap wrap-anywhere font-code text-xs leading-relaxed text-ink">{trace.reasoning}</pre>
        </details>}
        <div className="mt-3 rounded-lg border border-line bg-canvas p-3">
          <div className="flex items-center justify-between gap-2"><strong className="text-xs">Live model response</strong>
            <span className="text-xs text-muted">{trace.output.length} characters</span></div>
          <pre tabIndex={0} role="region" aria-label="Live model response text"
            className="mt-3 max-h-[320px] min-h-20 overflow-auto whitespace-pre-wrap wrap-anywhere font-code text-xs leading-relaxed text-ink">{trace.output || "Waiting for the first response text…"}</pre>
          {trace.issue && <p className={ui.warningNote} role="alert">{trace.issue}</p>}
        </div>
      </section>}
      <div className="mt-4 flex items-center justify-between gap-3">
        <h3 className="text-xs font-semibold">Events · {events.length}</h3>
        <button className={ui.button} onClick={copyLog} disabled={!events.length}>
          {copied ? <Check size={14} /> : <Copy size={14} />}{copied ? "Copied" : "Copy inspector"}
        </button>
      </div>
      <ol tabIndex={0} className="mt-3 max-h-[36vh] overflow-y-auto overscroll-contain rounded-lg border border-line bg-canvas p-2" aria-label="LLM activity events">
        {events.length ? events.map((event) => <li key={event.id}
          className="group grid grid-cols-[85px_100px_1fr] gap-2 border-b border-line px-2 py-3 text-xs leading-relaxed last:border-0 mobile:grid-cols-[85px_1fr]"
          data-type={event.type}>
          <time className="font-code text-muted">{timestamp(event.timestamp)}</time>
          <span className="font-semibold capitalize text-accent group-data-[type=error]:text-danger group-data-[type=success]:text-success group-data-[type=pause]:text-warning">{event.type}</span>
          <span className="wrap-anywhere text-ink mobile:col-span-2">{event.message}</span>
        </li>) : <li className="p-5 text-center text-xs text-muted">No runtime events have been recorded.</li>}
      </ol>
    </div>
  </dialog>;
}
