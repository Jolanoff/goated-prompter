import { useState } from "react";
import { ui } from "../../ui.js";
import { useWorkspace } from "./useWorkspace.js";
import RefineTab from "./RefineTab.jsx";
import { PromptText } from "../../shared/workflow/WorkflowControls.jsx";
import { useWorkflowSettings } from "../../shared/workflow/useWorkflowSettings.js";
import WorkflowSettingsStatus from "../../shared/workflow/WorkflowSettingsStatus.jsx";

/** Hosts Refine while App continues to own the single global job. */
export default function CreativeWorkspace(props) {
  const workspace = useWorkspace(props.job, props.onReceiveJob);
  const refineSettings = useWorkflowSettings("refine");
  const [starting, setStarting] = useState(false);
  const visible = props.view === "refine";
  const current = workspace.snapshot?.versions.find((version) => version.id === workspace.snapshot.current_id);
  const disabled = props.busy || workspace.pending || starting;
  async function generate(operation, payload) {
    if (disabled || !workspace.snapshot) return false;
    setStarting(true);
    workspace.setError("");
    try {
      await refineSettings.flush();
      return await props.onGenerate(operation, { ...payload, revision: payload.revision ?? workspace.snapshot.revision });
    } catch (err) {
      if (err.status === 409) await workspace.refresh();
      workspace.setError(err.message);
      return false;
    } finally { setStarting(false); }
  }
  const shared = { ...props, workspace, current, disabled, canGenerate: !props.noEngine,
    targets: props.inputs.target_model[0], lengths: props.inputs.prompt_length[0], onGenerate: generate };
  return <div hidden={!visible}>
    <div className={ui.pageHeading}><div>
      <h2>Refine your prompt</h2>
      <p>Paste a prompt or send one from Builder, then describe what to refine.</p>
    </div></div>
    {workspace.error && <div className={ui.message} role="alert"><span>{workspace.error}</span>
      <button className={ui.retryButton} onClick={async () => { if (await workspace.refresh()) workspace.setError(""); }}>Refresh workspace</button>
    </div>}
    {props.job?.result?.recovery_prompt && <section className={`${ui.panel} mb-5`}>
      <h3 className="mb-3 font-bold">Recovered result — not saved</h3>
      <PromptText text={props.job.result.recovery_prompt} label="Recovered prompt" />
      <button className={`${ui.button} mt-3`} onClick={() => props.onCopy(props.job.result.recovery_prompt)}>Copy recovered prompt</button>
    </section>}
    <div className={ui.workflowStatus}>
      <span>{props.noEngine ? "Choose a prompt engine in Builder or Settings to generate." : `Engine: ${props.engineLabel}`}</span>
      <span role="status">{props.active ? props.job.status === "cancelling" ? "Ending generation…" : props.job.progress || "Generating prompt…" : workspace.pending ? "Saving…" : "Ready"}</span>
      {props.active && <button className={ui.button} onClick={props.onCancel} disabled={props.job.status === "cancelling"}>End generation</button>}
    </div>
    {!workspace.snapshot ? <div className={ui.emptyState}><h2>Loading Refine</h2><p>Your prompt will appear here.</p></div> : <>
      <div hidden={props.view !== "refine"}>
        <WorkflowSettingsStatus settings={refineSettings} label="Refine" />
        {refineSettings.draft && <RefineTab {...shared} preferences={refineSettings} disabled={disabled || refineSettings.working} />}
      </div>
    </>}
  </div>;
}
