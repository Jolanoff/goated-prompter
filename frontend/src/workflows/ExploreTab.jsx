import { Copy, Layers3 } from "lucide-react";
import { ui } from "../ui.js";
import { DetailLocks, PromptText, TargetSelect } from "./WorkflowControls.jsx";
import ResolutionControl from "../ResolutionControl.jsx";
import { defaultResolution, resolutionError, resolutionLabel } from "../resolution.js";
import AdvancedInstructions from "./AdvancedInstructions.jsx";

const directions = [
  ["faithful", "Faithful", "Close to your source. Clearer and more precise."],
  ["creative", "Creative", "Fresh visual choices, with your core idea intact."],
  ["experimental", "Experimental", "Bolder presentation of the same scene."],
];

export default function ExploreTab({ workspace, current, disabled, canGenerate, builderPrompt, builderIdea, builderTarget,
  targets, lengths, onGenerate, onCopy, onNavigate, preferences, builderResolution, resolutions, onSavePrompt, canSavePrompt }) {
  const { base, target, length, locks, selected_id: selectedId, resolution } = preferences.draft;
  const setBase = (value) => preferences.update({ base: value });
  const setTarget = (value) => preferences.update({ target: value });
  const setLength = (value) => preferences.update({ length: value });
  const setLocks = (value) => preferences.update({ locks: value });
  const setSelectedId = (value) => preferences.update({ selected_id: value });
  const batches = workspace.snapshot.comparisons;
  const batch = batches.find((item) => item.id === selectedId) || batches.at(-1);
  function useSource(text, model, size) { preferences.update({ base: text, target: model, resolution: size || defaultResolution() }); }
  return <>
    <div className={ui.pageHeading}><div>
      <div className={ui.eyebrow}>ONE IDEA. THREE DIRECTIONS.</div>
      <h2>Explore the possibilities<span>.</span></h2>
      <p>Compare real visual directions, then take your favorite into Refine.</p>
    </div></div>
    <section className={ui.panel}>
      <div className="mb-4 flex flex-wrap gap-2">
        <button className={ui.button} disabled={disabled || !builderPrompt.trim()} onClick={() => useSource(builderPrompt, builderTarget, builderResolution)}>Use Builder prompt</button>
        <button className={ui.button} disabled={disabled || !builderIdea.trim()} onClick={() => useSource(builderIdea, builderTarget, builderResolution)}>Use Builder idea</button>
        <button className={ui.button} disabled={disabled || !current} onClick={() => useSource(current.prompt, current.target, current.resolution)}>Use current refinement</button>
      </div>
      <label className={ui.field}><span>Idea or prompt to explore</span>
        <textarea className={ui.ideaInput} value={base} maxLength={100000} disabled={disabled} onChange={(event) => setBase(event.target.value)}
          placeholder="Describe an idea, paste a prompt, or import one above…" />
      </label>
      <div className="mt-4 grid max-w-xl grid-cols-2 gap-4">
        <TargetSelect value={target} onChange={setTarget} targets={targets} disabled={disabled} label="Explore target model" />
        <label className={ui.field}><span>Direction length</span>
          <select className={ui.select} value={length} disabled={disabled} onChange={(event) => setLength(event.target.value)}>
            {lengths.map((item) => <option key={item}>{item}</option>)}
          </select>
        </label>
      </div>
      <DetailLocks value={locks} onChange={setLocks} disabled={disabled} prefix="Explore" />
      <ResolutionControl value={resolution} onChange={(value) => preferences.update({ resolution: value })} catalog={resolutions} disabled={disabled} prefix="Explore" />
      <p className="mt-3 text-xs leading-relaxed text-muted">All three keep your stated subjects, setting, action and medium. Creative and Experimental vary how the same scene is presented. Only Ideogram4 uses JSON output.</p>
      <p className="mt-3 text-xs leading-relaxed text-muted">Three sequential generations share one model session. Each completed direction is saved immediately. References are represented by the source text; import a reference-grounded Builder prompt to explore it.</p>
      <button className={ui.primaryButton} disabled={disabled || !canGenerate || !base.trim() || !!resolutionError(resolution, resolutions)} onClick={async () => {
        if (await onGenerate("explore", { base, locks, settings: { target_model: target, prompt_length: length, resolution } })) setSelectedId("");
      }}><Layers3 size={16} />Explore three directions</button>
    </section>
    <AdvancedInstructions settings={preferences} label="Explore" disabled={disabled} />
    <section className="mt-6" aria-label="Direction comparison">
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <label className={`${ui.field} min-w-0 flex-1`}><span>Saved comparisons</span>
          <select className={ui.select} value={batch?.id || ""} disabled={!batches.length} onChange={(event) => setSelectedId(event.target.value)}>
            {!batches.length && <option value="">No comparisons yet</option>}
            {[...batches].reverse().map((item) => <option key={item.id} value={item.id}>
              {new Date(item.created_at).toLocaleString()} · {item.target} · {item.base.slice(0, 65)}
            </option>)}
          </select>
        </label>
        {batch && <button className={ui.button} disabled={disabled} onClick={async () => {
          if (window.confirm("Delete this saved comparison? Versions already sent to Refine are kept.")) {
            if (await workspace.mutate({ action: "delete_comparison", id: batch.id })) setSelectedId("");
          }
        }}>Delete comparison</button>}
      </div>
      {batch && <details className="mb-4 text-xs"><summary className="cursor-pointer">Source & locks · {batch.results.length}/3 directions saved</summary>
        <p className="my-3 text-muted">{batch.target} · {resolutionLabel(batch.resolution)} · Locks: {batch.locks.join(", ") || "None"}</p>
        <PromptText text={batch.base} label="Comparison source" />
      </details>}
      <div className="grid grid-cols-3 items-stretch gap-4 [@media(width<=1100px)]:grid-cols-1">
        {directions.map(([key, label, description]) => {
          const result = batch?.results.find((item) => item.direction === key);
          return <article key={key} className={`${ui.panel} flex flex-col`} aria-label={`${label} direction`}>
            <h3 className="font-display text-lg font-bold text-[#d7c9ff]">{label}</h3>
            <p className="mb-4 mt-2 text-xs leading-relaxed text-muted">{description}</p>
            {result ? <>
              <PromptText text={result.prompt} label={`${label} prompt`} />
              <div className="mt-auto flex flex-wrap gap-2 pt-4">
                <button className={ui.button} onClick={() => onCopy(result.prompt)}><Copy size={15} />Copy</button>
                <button className={ui.saveButton} disabled={!canSavePrompt} onClick={() => onSavePrompt(result.prompt, batch.target, `${label} direction`, batch.resolution)}>Save prompt</button>
                <button className={ui.saveButton} disabled={disabled} onClick={async () => {
                  if (await workspace.mutate({ action: "add", prompt: result.prompt, target: batch.target, locks: batch.locks, resolution: batch.resolution })) onNavigate("refine");
                }}>Refine this direction</button>
              </div>
            </> : <p className="py-8 text-xs text-muted">{batch ? "This direction has not been saved. If generation stopped, your completed directions are still available." : "Your direction will appear here."}</p>}
          </article>;
        })}
      </div>
    </section>
  </>;
}
