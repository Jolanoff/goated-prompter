import { useEffect, useRef, useState } from "react";
import { Copy, Film, RefreshCw, SlidersHorizontal, Sparkles, Trash2 } from "lucide-react";
import { ui } from "../ui.js";
import { orderDisplayPresets, presetDisplayLabel } from "../presetPresentation.js";
import { TargetSelect } from "./WorkflowControls.jsx";
import { useWorkflowSettings } from "./useWorkflowSettings.js";
import WorkflowSettingsStatus from "./WorkflowSettingsStatus.jsx";
import { insertReference, insertShot, nextReference, nextShot, parseReferences, parseShots, referenceLimits } from "./minimaxReferences.js";

const modes = [["auto", "Auto"], ["T2VA", "Text to Video"], ["I2VA", "First Frame"],
  ["FL2VA", "First + Last Frame"], ["L2VA", "Last Frame"], ["Ref2VA", "Full Reference"]];
const models = ["MiniMax H3"];
const ratios = ["Auto", "16:9", "9:16", "1:1", "4:3", "3:4", "21:9"];

export default function MiniMaxTab({ visible, job, busy, active, noEngine, engineLabel, presets, onGenerate, onCancel, onCopy, onReleaseJobs }) {
  const preferences = useWorkflowSettings("minimax");
  const { draft, update } = preferences;
  const textarea = useRef(null);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState("");
  const submission = useRef(false);

  async function clearDraft() {
    // Retain the acknowledgement ID until cleanup finishes so a still-visible
    // terminal snapshot cannot rehydrate the output we just discarded.
    update({ user_request: "", generated_prompt: "", references: [] });
    setError("");
    try { await preferences.flush(); await onReleaseJobs?.("minimax"); }
    catch (err) { setError(`Could not release temporary job checkpoints. ${err.message}`); }
  }
  useEffect(() => {
    if (draft && job?.kind === "minimax" && job.status === "succeeded" && draft.result_job_id !== job.id) {
      update({ generated_prompt: job.result.prompt, result_job_id: job.id });
    }
  }, [draft, job, update]);

  const disabled = busy || starting || preferences.working;
  const parsed = parseReferences(draft?.user_request || "");
  const parsedShots = parseShots(draft?.user_request || "");
  const audioOnly = draft?.references.length > 0 && draft.references.every((token) => token.startsWith("audio"));
  const availablePresets = orderDisplayPresets(presets || []);
  const director = availablePresets.find((item) => item.id === draft?.director_preset);
  const missingReferences = parsed.references.filter((token) => !draft?.references.includes(token));
  const canGenerate = draft && !disabled && !noEngine && !preferences.conflict && director && draft.user_request.trim() && !parsed.invalid.length && !missingReferences.length && !parsedShots.invalid.length && parsedShots.ordered;

  function insert(token, references = draft.references) {
    const input = textarea.current;
    const focused = document.activeElement === input;
    const next = insertReference(draft.user_request, token,
      focused ? input.selectionStart : draft.user_request.length,
      focused ? input.selectionEnd : draft.user_request.length);
    update({ user_request: next.text, references });
    requestAnimationFrame(() => { input.focus(); input.setSelectionRange(next.cursor, next.cursor); });
  }
  function preserveCursor(event) {
    if (document.activeElement === textarea.current) event.preventDefault();
  }
  function addShot() {
    const input = textarea.current;
    const focused = document.activeElement === input;
    const token = nextShot(draft.user_request);
    const next = insertShot(draft.user_request, token,
      focused ? input.selectionStart : draft.user_request.length,
      focused ? input.selectionEnd : draft.user_request.length);
    update({ user_request: next.text });
    requestAnimationFrame(() => { input.focus(); input.setSelectionRange(next.cursor, next.cursor); });
  }
  function editRequest(value) {
    const typed = parseReferences(value).references;
    if (typed.length > 12) {
      // Keep the user's text, but never silently register unsupported references.
      update({ user_request: value });
      setError("MiniMax H3 supports 12 combined references. Clear the draft to start a new reference set.");
    } else {
      update({ user_request: value, references: typed });
      setError("");
    }
  }
  async function generate() {
    if (!canGenerate || submission.current) return;
    submission.current = true;
    setStarting(true);
    setError("");
    try {
      await preferences.flush();
      const { generated_prompt, result_job_id, ...input } = draft;
      await onGenerate("minimax", { input });
    } catch (err) { setError(err.message); }
    finally { submission.current = false; setStarting(false); }
  }

  return <div hidden={!visible}>
    <div className={ui.pageHeading}>
      <div>
        <h2>MiniMax H3</h2>
        <p>Describe the scene. Build a copy-ready prompt with motion, references and sound.</p>
      </div>
    </div>
    <WorkflowSettingsStatus settings={preferences} label="MiniMax H3" />
    {error && <div className={ui.message} role="alert">{error}</div>}
    <div className={ui.workflowStatus}>
      <span>{noEngine ? "Choose a prompt engine in Builder or Settings to generate." : `Engine: ${engineLabel}`}</span>
      <span role="status">{active ? job.status === "cancelling" ? "Ending generation…" : job.progress || "Generating prompt…" : "Prompt writing only · symbolic references"}</span>
      {active && <button className={ui.button} onClick={onCancel} disabled={job.status === "cancelling"}>End generation</button>}
    </div>
    {draft && <div className="grid grid-cols-[minmax(230px,0.7fr)_minmax(0,1.6fr)] items-start gap-6 [@media(width<=850px)]:grid-cols-1">
      <section className={ui.panel} aria-label="MiniMax settings">
        <header className={ui.panelHeader}>
          <div className={ui.panelIcon}><SlidersHorizontal size={21} /></div>
          <div className={ui.panelHeading}><h2>Scene settings</h2><p>A few choices to shape your prompt.</p></div>
        </header>
        <div className={ui.fields}>
          <TargetSelect label="Model" value={draft.model} targets={models} disabled={disabled} onChange={(model) => update({ model })} />
          <label className={ui.field}><span>Clip Length</span>
            <select className={ui.select} aria-label="Clip Length" value={draft.duration_seconds} disabled={disabled} onChange={(event) => update({ duration_seconds: Number(event.target.value) })}>
              {Array.from(new Set([4, 5, 6, 8, 10, 12, 15, draft.duration_seconds])).sort((a, b) => a - b).map((duration) => <option key={duration} value={duration}>{duration} seconds</option>)}
            </select>
          </label>
          <label className={ui.field}><span>Mode</span>
            <select className={ui.select} aria-label="Mode" value={draft.mode} disabled={disabled} onChange={(event) => update({ mode: event.target.value })}>
              {modes.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
          </label>
          <label className={ui.field}><span>Aspect ratio</span>
            <select className={ui.select} aria-label="Aspect Ratio" value={draft.aspect_ratio} disabled={disabled}
              onChange={(event) => update({ aspect_ratio: event.target.value })}>
              {ratios.map((ratio) => <option key={ratio}>{ratio}</option>)}
            </select>
          </label>
          <label className={ui.field}><span>Director Preset</span>
            <select className={ui.select} aria-label="Director Preset" aria-describedby="minimax-director-description" value={draft.director_preset} disabled={disabled} onChange={(event) => update({ director_preset: event.target.value })}>
              {!director && <option value={draft.director_preset}>Unavailable Director — choose a preset</option>}
              {availablePresets.map((preset) => <option key={preset.id} value={preset.id}>{presetDisplayLabel(preset)}</option>)}
            </select>
            <small id="minimax-director-description" className={ui.directorDescription}>{director?.description}</small>
          </label>
        </div>
        <fieldset disabled={disabled} className="mt-5 min-w-0 border-t border-line pt-4">
          <legend className="pr-2 text-xs font-semibold">References</legend>
          <p className="mb-3 text-[11px] leading-relaxed text-muted">Add text tokens for the media you’ll reference in MiniMax. No uploads needed.</p>
          <div className="flex flex-wrap gap-2">
            {Object.keys(referenceLimits).map((kind) => {
              const next = nextReference(kind, draft.references);
              return <button key={kind} type="button" className={ui.button} disabled={!next}
                aria-describedby={`minimax-${kind}-limit`} onPointerDown={preserveCursor}
                onClick={() => insert(next, [...draft.references, next])}>+ {kind[0].toUpperCase() + kind.slice(1)}</button>;
            })}
          </div>
          <div className="mt-3 flex flex-wrap gap-2" role="group" aria-label="Registered references">
            {draft.references.map((token) => <button type="button" className={ui.button} key={token}
              onPointerDown={preserveCursor} onClick={() => insert(token)}>{`<${token}>`}</button>)}
          </div>
          {Object.entries(referenceLimits).map(([kind, limit]) => <p key={kind} id={`minimax-${kind}-limit`} className={ui.subtleNote} hidden={draft.references.filter((token) => token.startsWith(kind)).length < limit}>
            {draft.references.filter((token) => token.startsWith(kind)).length >= limit ? `${kind[0].toUpperCase() + kind.slice(1)} limit reached (${limit}).` : null}
          </p>)}
          {draft.references.length >= 12 && <p className={ui.warningNote}>Combined reference limit reached (12).</p>}
          {audioOnly && <p className={ui.warningNote} role="status">Audio cannot be the only reference modality. Add an image or video reference before using the prompt in MiniMax.</p>}
          {!!parsed.invalid.length && <p className={ui.warningNote} role="alert">Unsupported reference: {parsed.invalid.join(", ")}. Use image1–image9, video1–video3 or audio1–audio3.</p>}
        </fieldset>
        <fieldset disabled={disabled} className="mt-5 min-w-0 border-t border-line pt-4">
          <legend className="pr-2 text-xs font-semibold">Shots (optional)</legend>
          <p className="mb-3 text-[11px] leading-relaxed text-muted">Type &lt;shot1&gt;, &lt;shot2&gt; in order, or add one below. For example, &lt;shot1&gt; 0-3s then &lt;shot2&gt; for the rest of the clip. Untimed shots share the remaining length.</p>
          <button type="button" className={ui.button} onPointerDown={preserveCursor} onClick={addShot}>+ Shot</button>
          {!!parsedShots.invalid.length && <p className={ui.warningNote} role="alert">Unsupported shot shortcut: {parsedShots.invalid.join(", ")}. Use &lt;shot1&gt;, &lt;shot2&gt;, etc.</p>}
          {!parsedShots.ordered && <p className={ui.warningNote} role="alert">Shots must appear once each in order, starting with &lt;shot1&gt;.</p>}
        </fieldset>
      </section>
      <div className={ui.column}>
        <section className={ui.panel}>
          <header className={ui.panelHeader}>
            <div className={ui.panelIcon}><Film size={21} /></div>
            <div className={ui.panelHeading}><h2><label htmlFor="minimax-request">Describe your video</label></h2><p>Write naturally. Optionally split it with &lt;shot1&gt;, &lt;shot2&gt; and timing such as 0-3s.</p></div>
          </header>
          <textarea id="minimax-request" ref={textarea} className={ui.ideaInput} style={{ minHeight: 220 }}
            value={draft.user_request} maxLength={100000} disabled={disabled} onChange={(event) => editRequest(event.target.value)}
            placeholder="The person in <image1> performs the same dance and movement style as <video1>. Put them on a neon-lit rooftop at night. Use energetic electronic music and have the camera slowly orbit around them." />
          <button className={`${ui.primaryButton} w-full`} onClick={generate} disabled={!canGenerate}>
            <Sparkles size={17} />{starting || active && job?.kind === "minimax" ? "Writing prompt…" : "Generate MiniMax prompt"}
          </button>
        </section>
        <section className={`${ui.panel} ${ui.outputPanel}`}>
          <header className={ui.panelHeader}>
            <div className={ui.panelIcon}><Sparkles size={21} /></div>
            <div className={ui.panelHeading}><h2><label htmlFor="minimax-output">Generated MiniMax H3 Prompt</label></h2><p>Edit the result or copy it straight into your MiniMax workflow.</p></div>
          </header>
          <textarea id="minimax-output" className={ui.outputInput} style={{ minHeight: 360 }} value={draft.generated_prompt}
            maxLength={100000} disabled={disabled} onChange={(event) => update({ generated_prompt: event.target.value })}
            placeholder="Your MiniMax H3 prompt will appear here." />
          <div className={ui.outputActions}>
            <button className={ui.button} disabled={!draft.generated_prompt} onClick={() => onCopy(draft.generated_prompt)}><Copy size={14} />Copy</button>
            <button className={ui.button} disabled={!canGenerate} onClick={generate}><RefreshCw size={14} />Regenerate</button>
            <button className={ui.button} disabled={disabled} onClick={clearDraft}><Trash2 size={14} />Clear</button>
          </div>
        </section>
      </div>
    </div>}
  </div>;
}
