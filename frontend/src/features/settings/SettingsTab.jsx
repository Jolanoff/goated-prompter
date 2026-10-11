import { ArrowLeft, Layers3, RefreshCw, Save } from "lucide-react";
import { Panel, Toggle } from "../../components/StudioPrimitives.jsx";
import { ui } from "../../ui.js";

export default function SettingsTab({ backend, models, draft, onChange, profiles,
  configuredBackend, busy, saving, actionBusy, onSave, onModelAction, onBack }) {
  return (
    <>
      <div className={ui.pageHeading}>
        <div><h2>Settings</h2><p>Connect your local models and choose how they run.</p></div>
        <button className={ui.button} onClick={onBack}>
          <ArrowLeft size={16} />Back to builder
        </button>
      </div>
      <form onSubmit={onSave} className={ui.settingsForm}>
        <fieldset disabled={busy || saving || actionBusy}>
          <Panel icon={Layers3} title="Local models" subtitle={`Configured backend: ${backend}`}>
            <label className={ui.field}>
              <span>Models directory</span>
              <input className={ui.input} required value={draft.models_directory || ""}
                aria-describedby="folder-help"
                onChange={(event) => onChange("models_directory", event.target.value)} />
            </label>
            <p className={ui.subtleNote} id="folder-help">
              Enter an existing folder path on the server. This folder
              is scanned directly and recursively; no LLM folder is
              appended. Put each model GGUF and its matching mmproj GGUF
              in the same subfolder. A folder containing the pair
              directly also works. Only complete vision-ready profiles
              appear in Prompt engine.
            </p>
            <Toggle label="Keep model loaded"
              description="Retain the model between generations for faster reuse."
              checked={draft.keep_model_loaded}
              onChange={(value) => onChange("keep_model_loaded", value)} />
            <div className="mt-[22px] flex flex-wrap items-center gap-2">
              <button className={ui.primaryButton} type="submit">
                <Save size={14} />{saving ? "Saving..." : "Save settings"}
              </button>
              <button className={ui.button} type="button" onClick={() => onModelAction()}>
                <RefreshCw size={14} />Refresh models
              </button>
              <button className={ui.button} type="button" onClick={() => onModelAction(true)}>
                <Layers3 size={14} />Unload model
              </button>
            </div>
            {busy && <p className={ui.warningNote}>
              Settings are read-only while a generation job is active.
              Return to the builder to manage the job.
            </p>}
            <p className={`${ui.subtleNote} wrap-anywhere`}>Scanned folder: {models.root}</p>
            <p className={ui.subtleNote}>
              {profiles.length} ready prompt engines found.
              {configuredBackend && " Generation uses your configured backend, even without local models."}
            </p>
            {models.profiles.filter((item) => !item.vision_ready).map((item) => (
              <p className={ui.warningNote} key={item.id}>
                {item.label}: incomplete model. Add the model GGUF and
                matching mmproj to the same folder, then refresh models.
              </p>
            ))}
            {models.warnings.map((warning, index) => (
              <p className={ui.warningNote} key={index}>{warning}</p>
            ))}
          </Panel>
        </fieldset>
      </form>
    </>
  );
}
