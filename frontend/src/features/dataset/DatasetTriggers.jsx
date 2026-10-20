import { Plus, Tag, Trash2 } from "lucide-react";
import { ui } from "../../ui.js";
import { maxTriggers, triggerExpansions, triggerKinds } from "./options.js";

const blank = () => ({ text: "", kind: "character", expand: "off", start: false });

/** The Dataset's trigger list: each trigger says what it is and how the prompts use it. */
export default function DatasetTriggers({ triggers, onChange }) {
  const rows = triggers || [];
  const change = (index, patch) => onChange(rows.map((row, at) => at === index ? { ...row, ...patch } : row));
  const remove = (index) => onChange(rows.filter((_, at) => at !== index));

  return <section className="dataset-triggers" aria-label="Triggers">
    <div className="dataset-triggers-heading">
      <span><Tag size={14} aria-hidden="true" />Triggers (optional, for LoRA)</span>
      <button className={ui.button} type="button" onClick={() => onChange([...rows, blank()])}
        disabled={rows.length >= maxTriggers} aria-label="Add trigger"><Plus size={14} aria-hidden="true" />Add</button>
    </div>
    {rows.length === 0 && <small className={ui.directorDescription}>No triggers. Add one for each LoRA token, character tag or style word.</small>}
    {rows.map((row, index) => <div className="dataset-trigger-row" key={index}>
      <input className={ui.input} aria-label={`Trigger ${index + 1} text`} maxLength={1000} value={row.text}
        placeholder="Trigger text" onChange={(event) => change(index, { text: event.target.value })} />
      <select className={ui.select} aria-label={`Trigger ${index + 1} type`} value={row.kind}
        onChange={(event) => change(index, { kind: event.target.value })}>
        {triggerKinds.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
      </select>
      <select className={ui.select} aria-label={`Trigger ${index + 1} use`} value={row.expand}
        onChange={(event) => change(index, { expand: event.target.value })}>
        {triggerExpansions.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
      </select>
      <label className="dataset-trigger-pin">
        <input type="checkbox" aria-label={`Trigger ${index + 1} at start`} checked={row.start === true}
          disabled={row.expand === "on"} onChange={(event) => change(index, { start: event.target.checked })} />Start
      </label>
      <div className="dataset-trigger-actions">
        <button className={ui.iconButton} type="button" aria-label={`Remove trigger ${index + 1}`} title="Remove"
          onClick={() => remove(index)}><Trash2 size={14} aria-hidden="true" /></button>
      </div>
    </div>)}
    {rows.length > 0 && <small className={ui.directorDescription}>
      Exact text: the app puts the text in every prompt and nothing it covers is described (a character's looks, an
      outfit, the style). Meaning only: the model writes what it means in its own words. Start: the text goes first,
      in list order; otherwise it goes where its type belongs. The review shows which person each character or
      outfit trigger belongs to.
    </small>}
  </section>;
}
