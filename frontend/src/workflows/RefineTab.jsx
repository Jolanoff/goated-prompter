import { useEffect, useState } from "react";
import { Copy, WandSparkles } from "lucide-react";
import { ui } from "../ui.js";
import { DetailLocks, PromptText, TargetSelect } from "./WorkflowControls.jsx";
import VersionHistory, { VersionDiff } from "./VersionHistory.jsx";

const quickActions = [
  ["More natural", "Make the language more natural and the scene more believable. Preserve all unrelated details."],
  ["More cinematic", "Make the unlocked lighting and framing more cinematic. Keep all other details unchanged."],
  ["Shorten", "Shorten the prompt, keeping all essential visual details and locked facts."],
  ["Remove filler", "Remove redundant wording and generic quality buzzwords. Preserve the concrete visual details."],
  ["Wider shot", "Pull the camera back for a wider shot. Preserve every unrelated detail."],
  ["Simplify background", "Simplify the background while preserving the subject and all unrelated details."],
];

export default function RefineTab({ workspace, current, disabled, canGenerate, builderPrompt, builderTarget, targets,
  onGenerate, onCopy, onUsePrompt }) {
  const [changes, setChanges] = useState("");
  const [locks, setLocks] = useState(["identity"]);
  const [source, setSource] = useState("");
  const [target, setTarget] = useState(builderTarget || "Generic");
  const [editing, setEditing] = useState(null);
  useEffect(() => {
    setLocks(current ? current.locks : ["identity"]);
  }, [current?.id]);
  const parent = workspace.snapshot.versions.find((version) => version.id === current?.parent_id);
  async function addSource(prompt, model) {
    const result = await workspace.mutate({ action: "add", prompt, target: model });
    if (result) setSource("");
  }
  return <>
    <div className={ui.pageHeading}><div>
      <div className={ui.eyebrow}>KEEP THE GOOD. REFINE THE REST.</div>
      <h2>Refine your prompt<span>.</span></h2>
      <p>Request a precise change, lock important details, and step back whenever you need.</p>
    </div></div>
    <div className="grid grid-cols-[minmax(0,2fr)_minmax(260px,1fr)] items-start gap-5 [@media(width<=1000px)]:grid-cols-1">
      <div className={ui.column}>
        <section className={ui.panel}>
          <h3 className="mb-3 font-display text-base font-bold">{current ? "Current version" : "Choose a starting prompt"}</h3>
          {current && <>
            <p className="mb-3 text-xs text-muted">{current.label} · {current.target}</p>
            <PromptText text={current.prompt} label="Current refinement prompt" />
            <div className={ui.inlineActions}>
              <button className={ui.button} onClick={() => onCopy(current.prompt)}><Copy size={15} />Copy prompt</button>
              <button className={ui.button} disabled={disabled} onClick={() => onUsePrompt(current.prompt, current.target)}>Use in Builder</button>
              <button className={ui.button} disabled={disabled} onClick={() => setEditing({ id: current.id, text: current.prompt })}>Edit text</button>
            </div>
            {editing && <div className="mt-4">
              <label className={ui.field}><span>Manual prompt edit</span>
                <textarea className={ui.outputInput} maxLength={100000} value={editing.text} disabled={disabled}
                  onChange={(event) => setEditing({ ...editing, text: event.target.value })} />
              </label>
              {editing.id !== current.id && <p className={ui.warningNote}>The current version changed. Your edit is kept here; copy it or cancel and edit the current version.</p>}
              <div className={ui.inlineActions}>
                <button className={ui.button} disabled={disabled || editing.id !== current.id || !editing.text.trim()} onClick={async () => {
                  if (await workspace.mutate({ action: "add", prompt: editing.text, target: current.target, edit: true })) setEditing(null);
                }}>Save as new version</button>
                <button className={ui.button} disabled={disabled} onClick={() => setEditing(null)}>Cancel edit</button>
              </div>
            </div>}
            {parent && <VersionDiff before={parent.prompt} after={current.prompt} />}
          </>}
          <details className="mt-4" open={!current || undefined}>
            <summary className="cursor-pointer text-xs font-semibold">Start from another prompt</summary>
            <p className="my-3 text-xs text-muted">Import Builder output or paste a prompt. Earlier versions remain in history.</p>
            <button className={ui.button} disabled={disabled || !builderPrompt.trim()} onClick={() => addSource(builderPrompt, builderTarget)}>Use Builder prompt</button>
            <label className={`${ui.field} mt-4`}><span>Starting prompt</span>
              <textarea className={ui.ideaInput} aria-label="Starting prompt" value={source} maxLength={100000} disabled={disabled}
                onChange={(event) => setSource(event.target.value)} placeholder="Paste the prompt you want to improve…" />
            </label>
            <div className="mt-3 max-w-xs"><TargetSelect value={target} onChange={setTarget} targets={targets} disabled={disabled} label="Starting prompt target" /></div>
            <button className={ui.primaryButton} disabled={disabled || !source.trim()} onClick={() => addSource(source, target)}>Start refining</button>
          </details>
        </section>
        <section className={ui.panel}>
          <h3 className="font-display text-base font-bold">What should change?</h3>
          <div className="my-4 flex flex-wrap gap-2">
            {quickActions.map(([label, instruction]) => <button key={label} className={ui.button} disabled={disabled || !current}
              onClick={() => setChanges((previous) => previous ? `${previous}\n${instruction}` : instruction)}>{label}</button>)}
          </div>
          <label className={ui.field}><span>Refinement instructions</span>
            <textarea className={ui.notesInput} value={changes} maxLength={10000} disabled={disabled || !current}
              onChange={(event) => setChanges(event.target.value)} placeholder="Make the lighting more dramatic, pull the camera back, and keep everything else." />
          </label>
          <DetailLocks value={locks} onChange={setLocks} disabled={disabled || !current} prefix="Refine" />
          <p className="mt-3 text-xs leading-relaxed text-muted">Locks guide the prompt engine; check the changes before using the result. This works from prompt text, including details already described from your references.</p>
          <button className={ui.primaryButton} disabled={disabled || !canGenerate || !current || !changes.trim() || !!editing}
            onClick={() => onGenerate("refine", { changes, locks, settings: { target_model: current.target, prompt_length: "Medium" } })}>
            <WandSparkles size={16} />Refine prompt
          </button>
          {editing && <p className={ui.subtleNote}>Save or cancel your manual edit before refining.</p>}
        </section>
      </div>
      <VersionHistory snapshot={workspace.snapshot} current={current} disabled={disabled || !!editing} onAction={workspace.mutate} />
    </div>
  </>;
}
