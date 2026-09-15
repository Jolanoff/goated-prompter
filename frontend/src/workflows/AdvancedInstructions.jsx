import { useEffect, useState } from "react";
import { ui } from "../ui.js";

const labels = { system: "System prompt", faithful: "Faithful direction", creative: "Creative direction", experimental: "Experimental direction" };

export default function AdvancedInstructions({ settings, label, disabled }) {
  const saved = settings.record.instructions;
  const serialized = JSON.stringify(saved);
  const [draft, setDraft] = useState(saved);
  const [section, setSection] = useState("system");
  const [notice, setNotice] = useState("");
  useEffect(() => { setDraft(JSON.parse(serialized)); }, [serialized]);
  const dirty = JSON.stringify(draft) !== serialized;
  const valid = Object.values(draft).every((value) => value.trim() && value.length <= 20000);
  return <details className={`${ui.panel} mt-5`}>
    <summary className="cursor-pointer text-sm font-semibold">{label} advanced settings</summary>
    <p className="my-3 text-xs leading-relaxed text-muted">Edit this workflow’s built-in behavior. Saved instructions apply to future generations. Target format, detail locks and resolution controls are applied separately.</p>
    <p className="mb-3 text-xs text-[#cbbbfa]">{Object.keys(settings.record.overrides).length ? "Using saved custom instructions" : "Using built-in instructions"}{dirty ? " · Unsaved edits" : ""}</p>
    <fieldset disabled={disabled || settings.working}>
      {Object.keys(saved).length > 1 && <label className={`${ui.field} mb-3`}><span>Instruction section</span>
        <select className={ui.select} aria-label={`${label} instruction section`} value={section} onChange={(event) => setSection(event.target.value)}>
          {Object.keys(saved).map((key) => <option key={key} value={key}>{labels[key]}</option>)}
        </select>
      </label>}
      <label className={ui.field}><span>{labels[section]}</span>
        <textarea className={ui.directorInput} aria-label={`${label} system prompt`} value={draft[section]} maxLength={20000}
          onChange={(event) => { setDraft({ ...draft, [section]: event.target.value }); setNotice(""); }} />
      </label>
      <div className={ui.inlineActions}>
        <button className={ui.saveButton} disabled={!dirty || !valid || settings.conflict} onClick={async () => {
          if (await settings.saveInstructions(draft)) setNotice("Instructions saved.");
        }}>Save {label} instructions</button>
        <button className={ui.button} disabled={!dirty} onClick={() => { setDraft(saved); setNotice(""); }}>Discard instruction edits</button>
        <button className={ui.button} disabled={(!dirty && !Object.keys(settings.record.overrides).length) || settings.conflict} onClick={async () => {
          if (window.confirm(`Restore all built-in ${label} instructions?`) && await settings.saveInstructions(null, true)) {
            setDraft(settings.record.defaults);
            setNotice("Built-in instructions restored.");
          }
        }}>Use built-in {label} instructions</button>
      </div>
    </fieldset>
    {notice && <p className="mt-3 text-xs text-[#a6eac2]" aria-live="polite">{notice}</p>}
  </details>;
}
