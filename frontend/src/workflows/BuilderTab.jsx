import { ArrowUpRight, Bookmark, ChevronDown, Copy, FileText, Layers3,
  LoaderCircle, LockKeyhole, SlidersHorizontal, Sparkles, Trash2, WandSparkles, X } from "lucide-react";
import { Panel } from "../components/StudioPrimitives.jsx";
import { orderDisplayPresets, presetDisplayLabel } from "../presetPresentation.js";
import { ui } from "../ui.js";

const taskLabels = {
  Enhance: "Improve a prompt",
  Archviz: "Architecture & interiors",
  Photography: "Photography",
  Character: "Character",
  Product: "Product",
  "Image Edit": "Edit an image",
  "Style Transfer": "Transfer a style",
  "Dataset Caption": "Caption for a dataset",
  Video: "Video shot",
  Custom: "Custom instructions",
};

function BuilderField({ name, label, schema, value, choices: override, onChange }) {
  const [type, options = {}] = schema;
  const choices = override || (Array.isArray(type)
    ? type.map((value) => ({ value, label: value })) : null);
  return (
    <label className={ui.field}>
      <span>{label}</span>
      {choices ? (
        <span className={ui.selectWrap}>
          <select className={ui.select} aria-label={label} value={value ?? ""}
            onChange={(event) => onChange(name, event.target.value)}>
            {choices.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
          </select><ChevronDown size={15} />
        </span>
      ) : (
        <input className={ui.input} aria-label={label} type={type === "INT" ? "number" : "text"}
          min={options.min} max={options.max} step={type === "INT" ? 1 : undefined} value={value ?? ""}
          onChange={(event) => onChange(name, type === "INT" && event.target.value !== ""
            ? Number(event.target.value) : event.target.value)} />
      )}
    </label>
  );
}

export default function BuilderTab({ settings, inputs, presets, preset, engine, job,
  busy, active, status, actionBusy, settingsBusy, uploading, canSave, hasImages,
  hasMissingReferences, onChange, onManagePresets, onSelectEngine, onNavigate,
  onCopy, onSave, onGenerate, onCancel, children }) {
  const prompt = settings.generated_prompt || "";
  const { backend, configuredBackend, selectedProfile, profiles, noEngine } = engine;
  const generationDisabled = busy || !!uploading || actionBusy || settingsBusy || noEngine;
  const field = (name, label, choices) => (
    <BuilderField name={name} label={label} schema={inputs[name]}
      value={settings[name]} choices={choices} onChange={onChange} />
  );
  return (
    <>
      <div className={ui.pageHeading}>
        <div><h2>Start with an idea.</h2>
          <p>Shape a rough thought into a ready-to-use image or video prompt.</p>
        </div>
        <span className={ui.workspaceTag}><Layers3 size={14} />Prompt workspace</span>
      </div>
      <fieldset disabled={busy}>
        <div className={ui.workspaceGrid}>
          <div className={ui.column}>
            <Panel icon={FileText} title="Describe your idea"
              subtitle="Start with the subject, mood, setting, or a little bit of everything." className={ui.ideaPanel}>
              <div className="relative">
                <textarea aria-label="Describe your idea" className={ui.ideaInput} value={settings.idea}
                  onChange={(event) => onChange("idea", event.target.value)}
                  placeholder="A cinematic portrait of a wandering samurai in a misty forest at dawn..." />
                <span className={ui.charCount}>{settings.idea.length.toLocaleString()} characters</span>
              </div>
              <div className={ui.inputHint}><Sparkles size={13} /><span>
                Start with a rough idea, then choose a task and saved instructions below.
              </span></div>
            </Panel>
            <Panel icon={SlidersHorizontal} title="Prompt controls" subtitle="Choose how your idea takes shape.">
              <div className={`${ui.fields} grid-cols-2`}>
                {field("mode", "Prompt task", inputs.mode[0].map((value) => ({ value, label: taskLabels[value] || value })))}
                {field("director_preset", "Instruction preset", orderDisplayPresets(presets).map((item) => ({
                  value: item.id, label: presetDisplayLabel(item),
                })))}
              </div>
              <div className="mb-5 border-t border-line pt-3">
                <p className={ui.subtleNote}>
                  Changing the task selects its matching instruction preset.
                  You can then choose another preset without changing the task.
                </p>
                <span className={ui.directorDescription}>
                  {preset?.description === "User Director" ? "User instruction preset" : preset?.description}
                </span>
                <button className={ui.textButton} onClick={onManagePresets}>Manage instruction presets</button>
              </div>
              {field("target_model", "Target model")}
              <div className={`${ui.fields} ${ui.threeFields} mt-5`}>
                {field("creativity", "Creativity")}
                {field("prompt_length", "Prompt length", ["Short", "Medium", "Detailed", "Maximum Detail"].map(
                  (value) => ({ value, label: value })))}
                <label className={ui.field}>
                  <span>Prompt engine</span><span className={ui.selectWrap}>
                    <select className={ui.select} aria-label="Prompt engine"
                      value={configuredBackend ? "configured" : selectedProfile?.id || ""}
                      disabled={settingsBusy || actionBusy || configuredBackend || noEngine}
                      onChange={(event) => onSelectEngine(event.target.value)}>
                      {configuredBackend ? <option value="configured">Configured backend ({backend})</option>
                        : profiles.length ? profiles.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)
                        : <option value="">No ready local engines</option>}
                    </select><ChevronDown size={15} />
                  </span>
                </label>
              </div>
              <p className={ui.subtleNote}>
                Maximum Detail uses the largest output budget, not a
                guaranteed word count. Actual length depends on the model and your instructions.
              </p>
              {noEngine && <p className={ui.warningNote}>
                No complete local model found.{" "}
                <button className={ui.textButton} onClick={() => onNavigate("settings")}>Set up models in Settings</button>
              </p>}
            </Panel>
            <Panel icon={FileText} title="Workflow rules / notes" subtitle="Add constraints or details the prompt should keep.">
              <textarea className={ui.notesInput} aria-label="Workflow rules"
                placeholder="e.g. Avoid text and watermarks. Keep natural lighting and realistic textures…"
                value={settings.custom_instructions}
                onChange={(event) => onChange("custom_instructions", event.target.value)} />
            </Panel>
          </div>
          <div className={ui.column}>
            <Panel icon={WandSparkles} title="Generated prompt"
              subtitle="Review, edit, and copy it into your creative workflow." className={ui.outputPanel}
              action={<span className={ui.resultStatus} data-working={active}>
                <span className={ui.statusDot} />{active ? status : prompt ? "Ready" : "Awaiting idea"}
              </span>}>
              <div className="relative">
                <textarea className={ui.outputInput} aria-label="Generated prompt" value={prompt}
                  onChange={(event) => onChange("generated_prompt", event.target.value)}
                  placeholder={"Your prompt will appear here.\n\nGenerate from your idea, then edit or copy the result."}
                  spellCheck={false} />
                <span className={ui.charCount}>{prompt.length.toLocaleString()} characters</span>
              </div>
              <div className={ui.outputActions}>
                <button className={ui.button} disabled={!prompt} onClick={() => onCopy(prompt)}>
                  <Copy size={16} />Copy Prompt
                </button>
                <button className={ui.saveButton} disabled={!prompt.trim() || !canSave} onClick={onSave}>
                  <Bookmark size={16} />Save Prompt
                </button>
                <button className={ui.button} disabled={!prompt} onClick={() => onChange("generated_prompt", "")}>
                  <Trash2 size={16} />Clear
                </button>
              </div>
              <div className={ui.inlineActions}>
                <button className={ui.button} disabled={!prompt.trim()} onClick={() => onNavigate("refine")}>
                  <WandSparkles size={15} />Refine & history
                </button>
              </div>
            </Panel>
            {children}
          </div>
        </div>
      </fieldset>
      <div className={ui.generationBar}>
        <button className={ui.generateButton} disabled={hasMissingReferences || generationDisabled}
          onClick={() => onGenerate(false)}>
          {busy ? <LoaderCircle size={25}
            className={job?.status === "paused" || job?.status === "cancelling" ? "" : "animate-working"} />
            : <Sparkles size={25} />}
          <span><strong>{busy ? status === "Pause requested" ? "Finishing current stage" : status : "Generate prompt"}</strong>
            <small>{busy ? "Your idea is in good hands" : hasImages
              ? "Create a prompt grounded in your references" : "Turn your idea into a refined prompt"}</small>
          </span>
        </button>
        <button className={ui.endButton} disabled={!active || actionBusy} onClick={onCancel}>
          <X size={23} /><span><strong>End generation</strong>
            <small>{job?.status === "cancelling" ? "Ending the active model request" : "Stop this generation now"}</small>
          </span>
        </button>
      </div>
      <div className={ui.belowActions}>
        <span><LockKeyhole size={12} />Settings and saved prompts stay in local JSON files on this server.</span>
        <button className={ui.textButton} disabled={generationDisabled || !settings.idea.trim()}
          onClick={() => onGenerate(true)}>Text-only preview<ArrowUpRight size={13} /></button>
        <span className={ui.previewNote}>Ignores reference images and the attributes selected to keep.</span>
      </div>
    </>
  );
}
