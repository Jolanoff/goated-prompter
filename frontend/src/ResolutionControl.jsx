import { ui } from "./ui.js";
import { defaultResolution, resolutionError } from "./resolution.js";

export default function ResolutionControl({ value, onChange, catalog, disabled, prefix }) {
  const resolution = value || defaultResolution();
  const error = resolutionError(resolution, catalog);
  return <fieldset disabled={disabled} className="mt-4 min-w-0">
    <legend className="text-xs font-semibold">Image / video resolution</legend>
    <div className="mt-3 grid grid-cols-3 gap-3 mobile:grid-cols-2">
      <label className={`${ui.field} mobile:col-span-full`}><span>Aspect ratio</span>
        <select aria-label={`${prefix} aspect ratio`} className={ui.select} value={resolution.aspect_ratio} onChange={(event) => {
          const ratio = event.target.value;
          onChange(ratio === "Auto" ? defaultResolution() : { ...resolution, aspect_ratio: ratio, ...(catalog?.presets[ratio] || {}) });
        }}>
          <option value="Auto">Auto — follow the idea</option>
          {Object.entries(catalog?.presets || {}).map(([ratio, size]) => <option key={ratio} value={ratio}>{ratio} · {size.width} × {size.height}</option>)}
          <option value="Custom">Custom width × height</option>
        </select>
      </label>
      {resolution.aspect_ratio !== "Auto" && ["width", "height"].map((key) => <label className={ui.field} key={key}>
        <span>{key === "width" ? "Width (px)" : "Height (px)"}</span>
        <input className={ui.input} aria-label={`${prefix} ${key}`} type="number" min={catalog?.min ?? 16} max={catalog?.max ?? 16384} step={1}
          disabled={resolution.aspect_ratio !== "Custom"} value={resolution[key]} aria-invalid={!!error}
          onChange={(event) => onChange({ ...resolution, [key]: event.target.value === "" ? "" : Number(event.target.value) })} />
      </label>)}
    </div>
    {error && <p className={ui.warningNote} role="alert">{error}</p>}
    <p className={ui.subtleNote}>Guides framing, subject scale and readable detail. Presets include pixel sizes; use Custom for your exact output. Set the same dimensions in your image/video generator.</p>
  </fieldset>;
}
