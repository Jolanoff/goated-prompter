import { useEffect, useRef } from "react";
import { Copy, RotateCcw, WandSparkles } from "lucide-react";
import { ui } from "../../ui.js";
import { DetailLocks, TargetSelect } from "../../shared/workflow/WorkflowControls.jsx";
import VersionDiff from "./VersionDiff.jsx";
import AdvancedInstructions from "./AdvancedInstructions.jsx";
import { quickActions } from "./options.js";

export default function RefineTab({ workspace, current, disabled, canGenerate, targets,
  builderImport, onGenerate, onCopy, onUsePrompt, preferences, onSavePrompt, canSavePrompt }) {
  const { changes, locks, source, target, editing, lock_version_id } = preferences.draft;
  const updatePreferences = preferences.update;
  const setChanges = (value) => preferences.update({ changes: typeof value === "function" ? value(changes) : value });
  const setLocks = (value) => preferences.update({ locks: value });
  const setSource = (value) => preferences.update({ source: value });
  const imported = useRef(null);
  useEffect(() => {
    if (builderImport && imported.current !== builderImport) {
      imported.current = builderImport;
      updatePreferences({ source: builderImport.prompt, target: builderImport.target, editing: null });
    }
  }, [builderImport, updatePreferences]);
  useEffect(() => {
    if (lock_version_id !== (current?.id || null)) updatePreferences({ locks: current ? current.locks : ["identity"], lock_version_id: current?.id || null });
  }, [current, lock_version_id, updatePreferences]);
  const parent = workspace.snapshot.versions.find((version) => version.id === current?.parent_id);
  const prompt = editing?.text ?? (source || current?.prompt || "");
  const promptTarget = editing || source ? target : current?.target || target;
  function changePrompt(value) {
    if (current) updatePreferences({ editing: { id: editing?.id || current.id, text: value }, source: "", target: promptTarget });
    else setSource(value);
  }
  function changeTarget(value) {
    updatePreferences({ target: value, ...(current
      ? { editing: { id: editing?.id || current.id, text: prompt }, source: "" }
      : { source: prompt }) });
  }
  async function refine() {
    let revision = workspace.snapshot.revision;
    if (!current || current.prompt !== prompt || current.target !== promptTarget) {
      const saved = await workspace.mutate({ action: "add", prompt, target: promptTarget, locks,
        edit: !!current && editing?.id === current.id && current.target === promptTarget });
      if (!saved) return;
      revision = saved.revision;
    }
    if (await onGenerate("refine", { changes, locks, revision,
      settings: { target_model: promptTarget, prompt_length: "Medium" } })) {
      updatePreferences({ source: "", editing: null });
    }
  }
  async function undo() {
    if ((editing || source) && prompt !== current?.prompt && !window.confirm("Discard your unsaved prompt changes and undo the refinement?")) return;
    if (await workspace.mutate({ action: "undo" })) updatePreferences({ source: "", editing: null });
  }
  return <div className={ui.workspaceGrid}>
      <div className={ui.column}>
        <section className={ui.panel}>
          <label className={ui.field}><span>Prompt</span>
            <textarea className={ui.outputInput} aria-label="Refinement prompt" value={prompt} maxLength={100000}
              disabled={disabled} onChange={(event) => changePrompt(event.target.value)}
              placeholder="Paste your prompt here, or send one from Builder…" />
          </label>
          <div className="my-4 max-w-xs"><TargetSelect value={promptTarget} onChange={changeTarget}
            targets={targets} disabled={disabled} label="Prompt target" /></div>
          <div className={ui.inlineActions}>
            <button className={ui.button} disabled={!prompt.trim()} onClick={() => onCopy(prompt)}><Copy size={15} />Copy prompt</button>
            <button className={ui.saveButton} disabled={!prompt.trim() || !canSavePrompt} onClick={() => onSavePrompt(prompt, promptTarget, "Refined prompt")}>Save prompt</button>
            <button className={ui.button} disabled={disabled || !prompt.trim()} onClick={() => onUsePrompt(prompt, promptTarget)}>Use in Builder</button>
            <button className={ui.button} disabled={disabled || !current?.parent_id} onClick={undo}><RotateCcw size={15} />Undo</button>
          </div>
          {editing && editing.id !== current?.id && <p className={`${ui.warningNote} mt-3`}>The saved prompt changed. Your draft is kept in this box.</p>}
          {parent && <VersionDiff before={parent.prompt} after={current.prompt} />}
        </section>
      </div>
      <div className={ui.column}>
        <section className={ui.panel}>
          <h3 className="font-display text-base font-bold">What should change?</h3>
          <div className="my-4 flex flex-wrap gap-2">
            {quickActions.map(([label, instruction]) => <button key={label} className={ui.button} disabled={disabled}
              onClick={() => setChanges((previous) => previous ? `${previous}\n${instruction}` : instruction)}>{label}</button>)}
          </div>
          <label className={ui.field}><span>Refinement instructions</span>
            <textarea className={ui.notesInput} value={changes} maxLength={10000} disabled={disabled}
              onChange={(event) => setChanges(event.target.value)} placeholder="Make the lighting more dramatic, pull the camera back, and keep everything else." />
          </label>
          <DetailLocks value={locks} onChange={setLocks} disabled={disabled} prefix="Refine" />
          <p className="mt-3 text-xs leading-relaxed text-muted">Locks guide the prompt engine; check the changes before using the result. This works from prompt text, including details already described from your references.</p>
          <button className={ui.primaryButton} disabled={disabled || !canGenerate || !prompt.trim() || !changes.trim()}
            onClick={refine}>
            <WandSparkles size={16} />Refine prompt
          </button>
        </section>
        <AdvancedInstructions settings={preferences} label="Refine" disabled={disabled} />
      </div>
  </div>;
}
