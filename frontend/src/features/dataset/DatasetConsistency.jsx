import { ChevronDown, Layers3 } from "lucide-react";
import { ui } from "../../ui.js";
import { consistencyLevels, consistencyParts, typeConsistency } from "./options.js";

const levelLabels = Object.fromEntries(consistencyLevels);

// What stays the same across the set, per part of the image. A part left on Auto follows the dataset type's default and
// the request; the draft stores only the parts set by hand.
export default function DatasetConsistency({ type, value, onChange }) {
  const chosen = value || {};
  const defaults = typeConsistency[type] || {};
  const held = consistencyParts.filter(([part]) => (chosen[part] || defaults[part] || "free") !== "free");

  function choose(part, level) {
    const next = { ...chosen };
    if (level === "auto") delete next[part];
    else next[part] = level;
    onChange(next);
  }

  return <details className="dataset-details dataset-advanced">
    <summary><Layers3 size={14} aria-hidden="true" /><span>Consistency</span>
      {held.length > 0 && <span className="dataset-rules-indicator">
        {held.map(([part, label]) => `${label}: ${levelLabels[chosen[part] || defaults[part]]}`).join(" · ")}</span>}
      <ChevronDown size={14} aria-hidden="true" /></summary>
    <div className="dataset-config-fields mt-4">
      <small className={ui.directorDescription}>What stays the same across the set. Locked: identical in every image.
        Themed: every image follows your words for it, the rest varies. Free: new in every image. Auto follows the
        dataset type, and your request can still lock or free a part it mentions.</small>
      <div className="dataset-consistency-grid">
        {consistencyParts.map(([part, label]) => <label key={part} className={ui.field}><span>{label}</span>
          <select className={ui.select} aria-label={`${label} consistency`} value={chosen[part] || "auto"}
            onChange={(event) => choose(part, event.target.value)}>
            <option value="auto">Auto ({levelLabels[defaults[part] || "free"]})</option>
            {consistencyLevels.map(([level, text]) => <option key={level} value={level}>{text}</option>)}
          </select>
        </label>)}
      </div>
    </div>
  </details>;
}
