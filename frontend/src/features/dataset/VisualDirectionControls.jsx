import { Film } from "lucide-react";
import { ui } from "../../ui.js";
import { VISUAL_DIMENSIONS, VISUAL_VARIATIONS, updateVisualDirection } from "./visualDirection.js";

/** Per-dimension Visual Direction controls for the next run. The brief's own camera and light wording always wins. */
export default function VisualDirectionControls({ settings, onChange, disabled, packAvailable = true }) {
  return <fieldset className="visual-direction" aria-label="Visual direction" disabled={disabled}>
    <legend><Film size={14} aria-hidden="true" />Visual direction</legend>
    <p className="visual-direction-help">Chooses a camera and light per image for what your request leaves open. What you write about
      the camera, framing or light is always kept; subjects and actions never change.</p>
    {!packAvailable && <p className="visual-direction-note" role="note">Select the Visual Direction pack above to use these settings.</p>}
    <ul>
      {VISUAL_DIMENSIONS.map(([id, label, help]) => {
        const item = settings[id];
        return <li key={id} data-enabled={item.enabled}>
          <label className={ui.toggleRow} title={help}>
            <input className={ui.toggleInput} type="checkbox" role="switch" aria-label={`Visual direction: ${label}`}
              checked={item.enabled} disabled={disabled} onChange={() => onChange(updateVisualDirection(settings, id, { enabled: !item.enabled }))} />
            <span className={ui.switch} /><span className={ui.toggleLabel}>{label}</span>
          </label>
          <select className={ui.select} aria-label={`${label} variation`} value={item.variation} disabled={disabled || !item.enabled}
            onChange={(event) => onChange(updateVisualDirection(settings, id, { variation: event.target.value }))}>
            {VISUAL_VARIATIONS.map(([value, text]) => <option key={value} value={value}>{text}</option>)}
          </select>
        </li>;
      })}
    </ul>
  </fieldset>;
}
