import { useState } from "react";
import { ui } from "../ui.js";
import { useWorkspace } from "./useWorkspace.js";
import RefineTab from "./RefineTab.jsx";
import ExploreTab from "./ExploreTab.jsx";
import { PromptText } from "./WorkflowControls.jsx";

/** Hosts the two independent tabs. App continues to own the single global job. */
export default function CreativeWorkspace(props) {
  const workspace = useWorkspace(props.job, props.onReceiveJob);
  const [starting, setStarting] = useState(false);
  const visible = props.view === "refine" || props.view === "explore";
  const current = workspace.snapshot?.versions.find((version) => version.id === workspace.snapshot.current_id);
  const disabled = props.busy || workspace.pending || starting;
  async function generate(operation, payload) {
    if (disabled || !workspace.snapshot) return false;
    setStarting(true);
    workspace.setError("");
    try {
      return await props.onGenerate(operation, { ...payload, revision: workspace.snapshot.revision });
    } catch (err) {
      if (err.status === 409) await workspace.refresh();
      workspace.setError(err.message);
      return false;
    } finally { setStarting(false); }
  }
  const shared = { ...props, workspace, current, disabled, canGenerate: !props.noEngine,
    targets: props.inputs.target_model[0], lengths: props.inputs.prompt_length[0], onGenerate: generate };
  return <div hidden={!visible}>
    {workspace.error && <div className={ui.message} role="alert"><span>{workspace.error}</span>
      <button className={ui.retryButton} onClick={async () => { if (await workspace.refresh()) workspace.setError(""); }}>Refresh workspace</button>
    </div>}
    {props.job?.result?.recovery_prompt && <section className={`${ui.panel} mb-5`}>
      <h3 className="mb-3 font-bold">Recovered result — not saved</h3>
      <PromptText text={props.job.result.recovery_prompt} label="Recovered prompt" />
      <button className={`${ui.button} mt-3`} onClick={() => props.onCopy(props.job.result.recovery_prompt)}>Copy recovered prompt</button>
    </section>}
    <div className="mb-5 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-line px-4 py-3 text-xs text-muted">
      <span>{props.noEngine ? "Choose a prompt engine in Builder or Settings to generate." : `Engine: ${props.engineLabel}`}</span>
      <span role="status">{props.active ? props.job.status === "cancelling" ? "Ending generation…" : props.job.progress || "Generating prompt…" : workspace.pending ? "Saving…" : "Versions & comparisons saved locally"}</span>
      {props.active && <button className={ui.button} onClick={props.onCancel} disabled={props.job.status === "cancelling"}>End generation</button>}
    </div>
    {!workspace.snapshot ? <div className={ui.emptyState}><h2>Loading your creative workspace</h2><p>Saved versions and comparisons will appear here.</p></div> : <>
      <div hidden={props.view !== "refine"}><RefineTab {...shared} /></div>
      <div hidden={props.view !== "explore"}><ExploreTab {...shared} /></div>
    </>}
  </div>;
}
