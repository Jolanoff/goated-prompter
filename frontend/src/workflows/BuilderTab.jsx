import { ArrowUpRight, Bookmark, ChevronDown, Copy,
  LoaderCircle, LockKeyhole, Sparkles, Trash2, WandSparkles, X } from "lucide-react";
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

function BuilderField({ name, label, short, schema, value, choices: override, onChange }) {
  const [type, options = {}] = schema;
  const choices = override || (Array.isArray(type)
    ? type.map((value) => ({ value, label: value })) : null);
  if (!choices) return (
    <label className={ui.field}>
      <span>{label}</span>
      <input className={ui.input} aria-label={label} type={type === "INT" ? "number" : "text"}
        min={options.min} max={options.max} step={type === "INT" ? 1 : undefined} value={value ?? ""}
        onChange={(event) => onChange(name, type === "INT" && event.target.value !== ""
          ? Number(event.target.value) : event.target.value)} />
    </label>
  );
  return (
    <label className={ui.pillField}>
      <span>{short || label}</span>
      <select aria-label={label} value={value ?? ""}
        onChange={(event) => onChange(name, event.target.value)}>
        {choices.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
      </select><ChevronDown size={14} aria-hidden="true" />
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
  const field = (name, label, short, choices) => (
    <BuilderField name={name} label={label} short={short} schema={inputs[name]}
      value={settings[name]} choices={choices} onChange={onChange} />
  );
  const working = status === "Pause requested" ? "Finishing current stage" : status;
  return (
    <>
      <div className={ui.pageHeading}>
        <div><h2>Start with an idea.</h2>
          <p>Shape a rough thought into a ready-to-use image or video prompt.</p>
        </div>
      </div>
      <div className={ui.workspaceGrid}>
        <div className={ui.column}>
          <section className={ui.composer}>
            <fieldset disabled={busy}>
              <header className={ui.panelHeader}>
                <div className={ui.panelHeading}><h2>Describe your idea</h2></div>
                <span className={ui.composerMeta}>{settings.idea.length.toLocaleString()} characters</span>
              </header>
              <textarea aria-label="Describe your idea" className={ui.ideaInput} value={settings.idea}
                onChange={(event) => onChange("idea", event.target.value)}
                placeholder="A cinematic portrait of a wandering samurai in a misty forest at dawn..." />
              <div className={ui.composerSection}>
                <h2 className={ui.composerLabel}>Prompt controls</h2>
                <div className={ui.pillGrid}>
                  {field("mode", "Prompt task", "Task", inputs.mode[0].map((value) => ({ value, label: taskLabels[value] || value })))}
                  {field("director_preset", "Instruction preset", "Preset", orderDisplayPresets(presets).map((item) => ({
                    value: item.id, label: presetDisplayLabel(item),
                  })))}
                  {field("target_model", "Target model", "Model")}
                  {field("creativity", "Creativity")}
                  {field("prompt_length", "Prompt length", "Length", ["Short", "Medium", "Detailed", "Maximum Detail"].map(
                    (value) => ({ value, label: value })))}
                  <label className={ui.pillField}>
                    <span>Engine</span>
                    <select aria-label="Prompt engine"
                      value={configuredBackend ? "configured" : selectedProfile?.id || ""}
                      disabled={settingsBusy || actionBusy || configuredBackend || noEngine}
                      onChange={(event) => onSelectEngine(event.target.value)}>
                      {configuredBackend ? <option value="configured">Configured backend ({backend})</option>
                        : profiles.length ? profiles.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)
                        : <option value="">No ready local engines</option>}
                    </select><ChevronDown size={14} aria-hidden="true" />
                  </label>
                </div>
                <p className={ui.composerNote}>
                  {preset?.description === "User Director" ? "User instruction preset." : preset?.description}
                  <button type="button" className={ui.textButton} onClick={onManagePresets}>Manage instruction presets</button>
                </p>
                {settings.prompt_length === "Maximum Detail" && <p className={ui.composerNote}>
                  Maximum Detail uses the largest output budget, not a guaranteed word count.
                </p>}
                {noEngine && <p className={ui.warningNote}>
                  No complete local model found.{" "}
                  <button type="button" className={ui.textButton} onClick={() => onNavigate("settings")}>Set up models in Settings</button>
                </p>}
              </div>
              <div className={ui.composerSection}>
                <label className={ui.field}>
                  <span className={ui.composerLabel}>Workflow rules / notes</span>
                  <textarea className={ui.notesInput} aria-label="Workflow rules"
                    placeholder="e.g. Avoid text and watermarks. Keep natural lighting and realistic textures…"
                    value={settings.custom_instructions}
                    onChange={(event) => onChange("custom_instructions", event.target.value)} />
                </label>
              </div>
            </fieldset>
            <div className={ui.composerActions}>
              <button className={ui.textButton} disabled={generationDisabled || !settings.idea.trim()}
                title="Ignores reference images and the attributes selected to keep."
                onClick={() => onGenerate(true)}>Text-only preview<ArrowUpRight size={13} /></button>
              <button className={ui.endButton} disabled={!active || actionBusy} onClick={onCancel}>
                <X size={16} /><span><strong>End generation</strong>
                  <small>{job?.status === "cancelling" ? "Ending the active model request" : "Stop this generation now"}</small>
                </span>
              </button>
              <button className={ui.generateButton} disabled={hasMissingReferences || generationDisabled}
                onClick={() => onGenerate(false)}>
                {busy ? <LoaderCircle size={20}
                  className={job?.status === "paused" || job?.status === "cancelling" ? "" : "animate-working"} />
                  : <Sparkles size={20} />}
                <span><strong>{busy ? working : "Generate prompt"}</strong>
                  <small>{busy ? "Your idea is in good hands" : hasImages
                    ? "Grounded in your references" : "Turn your idea into a prompt"}</small>
                </span>
              </button>
            </div>
          </section>
        </div>
        <div className={ui.column}>
          <section className={ui.resultDoc}>
            <fieldset disabled={busy} className="flex min-h-0 flex-1 flex-col">
              <header className={ui.panelHeader}>
                <div className={ui.panelHeading}><h2>Generated prompt</h2></div>
                <span className={ui.resultStatus} data-working={active} data-empty={!active && !prompt}>
                  <span className={ui.statusDot} />{active ? status : prompt ? "Ready" : "Awaiting idea"}
                </span>
                <span className={ui.composerMeta}>{prompt.length.toLocaleString()} characters</span>
              </header>
              <textarea className={ui.outputInput} aria-label="Generated prompt" value={prompt}
                onChange={(event) => onChange("generated_prompt", event.target.value)}
                placeholder={"Your prompt will appear here.\n\nGenerate from your idea, then edit or copy the result."}
                spellCheck={false} />
              <div className={ui.docToolbar}>
                <button className={ui.button} disabled={!prompt} onClick={() => onCopy(prompt)}>
                  <Copy size={15} />Copy Prompt
                </button>
                <button className={ui.saveButton} disabled={!prompt.trim() || !canSave} onClick={onSave}>
                  <Bookmark size={15} />Save Prompt
                </button>
                <button className={ui.button} disabled={!prompt.trim()} onClick={() => onNavigate("refine")}>
                  <WandSparkles size={15} />Refine & history
                </button>
                <button className={ui.iconButton} disabled={!prompt} aria-label="Clear" title="Clear"
                  onClick={() => onChange("generated_prompt", "")}>
                  <Trash2 size={16} />
                </button>
              </div>
            </fieldset>
          </section>
          <fieldset disabled={busy} className={ui.referenceStack}>{children}</fieldset>
        </div>
      </div>
      <p className={ui.belowActions}>
        <span><LockKeyhole size={12} />Settings and saved prompts stay in local JSON files on this server.</span>
      </p>
    </>
  );
}
