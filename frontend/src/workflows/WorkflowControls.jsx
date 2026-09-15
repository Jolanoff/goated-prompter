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
        className="flex cursor-pointer items-center gap-2 rounded-lg border border-line bg-[#11131b] px-3 py-2 text-xs has-checked:border-[#aa8cda] has-checked:text-[#d7c9ff]">
        <input type="checkbox" className="accent-[#aa8cda]" aria-label={`${prefix} lock ${label}`}
          checked={value.includes(key)} onChange={(event) => onChange(event.target.checked ? [...value, key] : value.filter((item) => item !== key))} />
        {label}
      </label>)}
    </div>
  </fieldset>;
}

export function TargetSelect({ value, onChange, targets, disabled, label = "Target model" }) {
  return <label className={ui.field}>
    <span>{label}</span>
    <select className={ui.select} value={value} onChange={(event) => onChange(event.target.value)} disabled={disabled}>
      {targets.map((target) => <option key={target}>{target}</option>)}
    </select>
  </label>;
}

export function PromptText({ text, label }) {
  return <pre aria-label={label} tabIndex={0}
    className="max-h-[460px] min-h-40 overflow-auto whitespace-pre-wrap wrap-anywhere rounded-lg border border-line bg-[#11131b] p-4 font-notes text-xs leading-[1.9] text-[#c6c7d9]">{text}</pre>;
}
