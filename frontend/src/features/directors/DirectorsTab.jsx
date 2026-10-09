import { FileText, Plus, RotateCcw, Save, Trash2, WandSparkles } from "lucide-react";
import { Panel } from "../../components/StudioPrimitives.jsx";
import { orderDisplayPresets, presetDisplayLabel } from "../../presetPresentation.js";
import { ui } from "../../ui.js";

export default function DirectorsTab({ library, directorId, draft, dirty, editorDirector,
  busy, actionBusy, onSelect, onChange, onWrite, onUse }) {
  return (
    <>
      <div className={ui.pageHeading}>
        <div><h2>Instruction presets</h2>
          <p>Reusable instructions that guide how your prompt task is written.</p>
        </div>
      </div>
      <div className={ui.directorsGrid}>
        <Panel icon={WandSparkles} title="Instruction presets" subtitle="Choose saved instructions to edit.">
          <div className={ui.directorList}>
            {orderDisplayPresets(library.presets).map((item) => (
              <button key={item.id}
                className={`${ui.directorChoice} ${directorId === item.id ? "selected" : ""}`}
                data-active={directorId === item.id} disabled={actionBusy}
                onClick={() => { if (item.id !== directorId) onSelect(item); }}>
                <strong>{presetDisplayLabel(item)}</strong>
                <span>{item.protected ? "Built-in" : "User"}{item.modified ? " / Edited" : ""}</span>
              </button>
            ))}
          </div>
          <button className={ui.button} disabled={busy || actionBusy} onClick={() => onSelect(null)}>
            <Plus size={15} />New instruction preset
          </button>
        </Panel>
        <form onSubmit={(event) => { event.preventDefault(); onWrite("save"); }}>
          <fieldset disabled={busy || actionBusy}>
            <Panel icon={FileText} title={directorId ? "Edit instruction preset" : "New instruction preset"}
              subtitle={dirty ? "Unsaved changes" : "Instructions saved separately from your builder."}>
              <label className={ui.field}>
                <span>Instruction preset name</span>
                <input className={ui.input} required maxLength={80} readOnly={!!editorDirector?.protected}
                  value={editorDirector?.protected ? presetDisplayLabel(editorDirector) : draft.name}
                  onChange={(event) => onChange("name", event.target.value)} />
              </label>
              {editorDirector?.protected && <p className={ui.subtleNote}>
                Built-in names cannot be changed. Instructions can be edited and restored.
              </p>}
              <p className={ui.subtleNote}>
                {editorDirector?.description === "User Director" ? "User instruction preset" : editorDirector?.description}
              </p>
              <label className={ui.field}>
                <span>Preset instructions</span>
                <textarea className={ui.directorInput} required value={draft.instructions}
                  onChange={(event) => onChange("instructions", event.target.value)} />
              </label>
              <div className={ui.inlineActions}>
                <button className={ui.primaryButton}
                  disabled={!dirty || !draft.name.trim() || !draft.instructions.trim()}>
                  <Save size={14} />Save changes
                </button>
                {editorDirector && <button type="button" className={ui.button} onClick={onUse}>
                  Use in builder
                </button>}
                {editorDirector && !editorDirector.protected &&
                  <button type="button" className={ui.button} onClick={() => onWrite("delete")}>
                    <Trash2 size={14} />Delete instruction preset
                  </button>}
                {editorDirector?.protected && editorDirector.modified &&
                  <button type="button" className={ui.button} onClick={() => onWrite("reset")}>
                    <RotateCcw size={14} />Reset built-in
                  </button>}
              </div>
              <p className={`${ui.subtleNote} wrap-anywhere`}>Stored JSON library: {library.storage}</p>
            </Panel>
          </fieldset>
          {busy && <p className={ui.warningNote}>
            Instruction presets are read-only while a generation job is active.
          </p>}
        </form>
      </div>
      {library.warnings?.map((warning, index) => (
        <p className={ui.warningNote} key={index}>{warning}</p>
      ))}
    </>
  );
}
