import { ui } from "../ui.js";

const lockOptions = [
  ["identity", "Identity / subject"], ["outfit", "Outfit"], ["pose", "Pose"],
  ["scene", "Setting"], ["composition", "Composition"], ["camera", "Camera"],
  ["lighting", "Lighting"], ["colors", "Colors"], ["materials", "Materials"], ["style", "Style"],
];

export function DetailLocks({ value, onChange, disabled, prefix }) {
  return <fieldset disabled={disabled} className="mt-5">
    <legend className="text-xs font-semibold">Keep these details</legend>
    <p className="my-2 text-xs leading-relaxed text-muted">Preserve these attributes from the source text. Locks take priority over requested changes.</p>
    <div className="flex flex-wrap gap-2">
      {lockOptions.map(([key, label]) => <label key={key}
        className={ui.choiceChip}>
        <input type="checkbox" aria-label={`${prefix} lock ${label}`}
          checked={value.includes(key)} onChange={(event) => onChange(event.target.checked ? [...value, key] : value.filter((item) => item !== key))} />
        {label}
      </label>)}
    </div>
  </fieldset>;
}

export function TargetSelect({ value, onChange, targets, disabled, label = "Target model", ariaLabel = label, icon }) {
  return <label className={ui.field}>
    <span>{icon}{label}</span>
    <select className={ui.select} aria-label={ariaLabel} value={value} onChange={(event) => onChange(event.target.value)} disabled={disabled}>
      {targets.map((target) => <option key={target}>{target}</option>)}
    </select>
  </label>;
}

export function PromptText({ text, label }) {
  return <pre role="region" aria-label={label} tabIndex={0}
    className={ui.promptText}>{text}</pre>;
}

export function PlanningSelect({ value = "Auto", onChange, disabled, video = false }) {
  const label = video ? "MiniMax planning" : "Builder planning";
  const help = video
    ? "Auto plans complex action and motion before writing the H3 prompt. Direct uses the original workflow. Always plans every request."
    : "Auto plans complex actions and spatial relationships before writing. Direct uses the original one-pass workflow. Always plans every request.";
  return <label className={ui.field} title={help}>
    <span>Planning</span>
    <select className={ui.select} aria-label={label} aria-describedby={video ? "minimax-planning-help" : "builder-planning-help"}
      value={value} disabled={disabled} onChange={(event) => onChange(event.target.value)}>
      {["Auto", "Direct", "Always"].map((mode) => <option key={mode}>{mode}</option>)}
    </select>
    <small id={video ? "minimax-planning-help" : "builder-planning-help"} className="sr-only">{help}</small>
  </label>;
}
