import { Box, Check, LockKeyhole, Package, RefreshCw, ShieldCheck, Trash2, Upload } from "lucide-react";
import { useRef, useState } from "react";
import { ui } from "../../ui.js";
import { useVocabularyPacks } from "./useVocabularyPacks.js";
import VocabularyExplorer from "./VocabularyExplorer.jsx";
import PackCreator from "./PackCreator.jsx";

const ratings = { general: "General", mature: "Mature", adult: "Adult" };
const origins = { core: "Mandatory Core", bundled: "Bundled", installed: "User-installed" };

function PackCard({ pack, busy, removing, onToggle, onUpdate, onRemove, onCancelRemove, onConfirmRemove }) {
  const name = pack.name || pack.id;
  return <li className="vocabulary-pack" data-problem={!!pack.problems.length}>
    <div className="vocabulary-pack-heading">
      <span className="vocabulary-pack-icon" aria-hidden="true">{pack.mandatory ? <LockKeyhole size={21} /> : <Box size={21} />}</span>
      <div className="vocabulary-pack-title"><h3>{name}</h3><span>{pack.id}</span></div>
      <span className="vocabulary-rating" data-rating={pack.rating || "unknown"}>
        <ShieldCheck size={13} aria-hidden="true" />{ratings[pack.rating] || "Rating unavailable"}
      </span>
    </div>
    <p className="vocabulary-description">{pack.description || (pack.valid ? "No description provided." : "Pack metadata could not be validated.")}</p>
    <dl className="vocabulary-metadata">
      <div><dt>Version</dt><dd>{pack.version || "Unavailable"}</dd></div>
      <div><dt>Entries</dt><dd>{pack.entries ?? "Unavailable"}</dd></div>
      <div><dt>Origin</dt><dd>{origins[pack.origin] || "Unknown"}</dd></div>
      <div className="vocabulary-dependencies"><dt>Dependencies</dt><dd>
        {Object.entries(pack.requires).length ? Object.entries(pack.requires).map(([id, version]) =>
          <span key={id}>{id} <span className="text-muted">{version}</span></span>) : "None"}
      </dd></div>
    </dl>
    {!!pack.problems.length && <div className="vocabulary-pack-problems" role="alert">
      <strong>Pack needs attention</strong><ul>{pack.problems.map((problem, index) => <li key={index}>{problem}</li>)}</ul>
    </div>}
    <div className="vocabulary-pack-actions">
      <label className={ui.toggleRow} title={pack.mandatory ? "Core is required and always enabled." : undefined}>
        <input className={ui.toggleInput} type="checkbox" role="switch" aria-label={`Enable ${name}`}
          checked={pack.enabled} disabled={busy || pack.mandatory || !pack.valid} onChange={() => onToggle(pack)} />
        <span className={ui.switch} /><span className={ui.toggleLabel}>{pack.mandatory ? "Always enabled" : pack.enabled ? "Enabled" : "Disabled"}</span>
      </label>
      {pack.bundled ? <span className="vocabulary-readonly"><LockKeyhole size={13} />Read-only files</span> :
        <div className={ui.inlineActions}>
          <button className={ui.button} disabled={busy} onClick={() => onUpdate(pack)}><Upload size={14} />Update ZIP</button>
          <button className={ui.button} disabled={busy} aria-label={`Remove ${name}`} onClick={() => onRemove(pack)}><Trash2 size={14} />Remove</button>
        </div>}
    </div>
    {removing && <div className="vocabulary-remove" role="group" aria-label={`Confirm removal of ${name}`}>
      <div><strong>Remove {name}?</strong><p>This deletes the installed pack files. Existing Dataset outputs are not changed.</p></div>
      <div className={ui.inlineActions}>
        <button className={ui.button} autoFocus disabled={busy} onClick={onCancelRemove}>Cancel</button>
        <button className={`${ui.button} text-danger`} disabled={busy} onClick={() => onConfirmRemove(pack)}>Remove pack</button>
      </div>
    </div>}
  </li>;
}

export function PackManagerView({ visible, state, heading = true }) {
  const { snapshot, loading, saving, error, notice, removing, target, file, reload, upload,
    setFile, chooseUpdate, setRemoving, toggle, remove } = state;
  const importer = useRef(null);
  const busy = loading || saving;
  const packs = (snapshot?.packs || []).filter((pack) => !pack.mandatory);
  function update(pack) {
    chooseUpdate(pack);
    importer.current?.scrollIntoView({ block: "center" });
    importer.current?.querySelector("input")?.focus();
  }
  return <section className="vocabulary-view" hidden={!visible} aria-label="Vocabulary pack manager" aria-busy={busy}>
    <div className={heading ? ui.pageHeading : "vocabulary-manager-toolbar"}>
      {heading && <div><h2>Vocabulary</h2><p>Give the scene Director more to draw from. You decide which packs are available.</p></div>}
      <button className={ui.button} disabled={busy} onClick={reload}><RefreshCw size={15} />Refresh packs</button>
    </div>
    <div className="vocabulary-guidance"><Package size={18} aria-hidden="true" />
      <p>Pack changes apply to the <strong>next Dataset run</strong>. Adult entries stay limited to eligible NSFW requests.</p>
    </div>
    <ul className="vocabulary-explainer" aria-label="How packs work">
      <li><strong>Enabled</strong><span>The Director can use its entries in the next Dataset run.</span></li>
      <li><strong>Disabled</strong><span>Kept on disk, but never offered. You can still browse it.</span></li>
      <li><strong>Optional content</strong><span>Install additional content packs as a ZIP; disable or remove them to turn them off. Core interfaces load internally.</span></li>
    </ul>
    <form ref={importer} className="vocabulary-import" onSubmit={async (event) => {
      event.preventDefault();
      const form = event.currentTarget;
      if (await upload()) form.reset();
    }}>
      <div><h3>{target ? `Update ${target.name || target.id}` : "Install a vocabulary pack"}</h3>
        <p>{target ? `Choose a ZIP with pack id “${target.id}”. Your current pack stays intact if validation fails.`
          : "Import a data-only ZIP. Schemas, dependencies and content ratings are checked before installation."}</p></div>
      <div className="vocabulary-import-controls">
        <label className={ui.field}><span>Pack ZIP{snapshot ? ` · up to ${snapshot.max_archive_bytes / (1024 * 1024)} MB` : ""}</span>
          <input key={target?.id || "install"} type="file" accept=".zip,application/zip" aria-label="Pack ZIP"
            disabled={busy} onChange={(event) => setFile(event.target.files?.[0] || null)} /></label>
        <div className={ui.inlineActions}>
          {target && <button type="button" className={ui.button} disabled={busy} onClick={() => chooseUpdate(null)}>Cancel update</button>}
          <button className={ui.primaryButton} disabled={busy || !file}><Upload size={15} />
            {saving ? "Applying changes…" : target ? "Update pack" : "Install ZIP"}</button>
        </div>
      </div>
    </form>
    {error && <div className={ui.message} role="alert"><span>{error}</span>
      <button className={ui.button} disabled={busy} onClick={reload}>Reload packs</button></div>}
    {notice && <p className="vocabulary-success" role="status"><Check size={16} />{notice}</p>}
    {loading && <p className="vocabulary-feedback" role="status">Loading vocabulary packs…</p>}
    {!!snapshot?.problems.length && <div className="vocabulary-pack-problems" role="alert">
      <strong>Vocabulary cannot load until these problems are resolved</strong>
      <ul>{snapshot.problems.map((problem, index) => <li key={index}>{problem}</li>)}</ul>
    </div>}
    {snapshot && <>
      <div className="vocabulary-library-heading"><h3>Pack library</h3>
        <span>{packs.filter((pack) => pack.enabled).length} enabled / {packs.length} available</span></div>
      {packs.length ? <ul className="vocabulary-packs" aria-label="Available vocabulary packs">
        {packs.map((pack) => <PackCard key={`${pack.origin}-${pack.id}`} pack={pack} busy={busy}
          removing={removing?.id === pack.id && removing?.origin === pack.origin} onToggle={toggle} onUpdate={update}
          onRemove={setRemoving} onCancelRemove={() => setRemoving(null)} onConfirmRemove={remove} />)}
      </ul> : <div className={ui.emptyState}><Package size={28} /><h3>No packs found</h3>
        <p>Install a content pack or restore the bundled packs, then refresh.</p></div>}
    </>}
    <footer className="vocabulary-footer">Creating a pack with your AI assistant? Keep using <code>vocabulary/SKILL.md</code>, then install its ZIP here.</footer>
  </section>;
}

const sections = [
  { id: "packs", title: "Packs", help: "Choose which vocabulary packs the Dataset Director can use, and install new ones." },
  { id: "test", title: "Test a request", help: "Type a request and see exactly which entries and ideas each Dataset image would be offered." },
  { id: "browse", title: "Browse", help: "Look up any entry: what it means, what it needs and where it comes from." },
  { id: "create", title: "Create a pack", help: "Build your own pack visually, test it, then export or install it." },
];

export default function VocabularyTab({ visible }) {
  const state = useVocabularyPacks(visible);
  const [section, setSection] = useState("packs");
  const packs = state.snapshot?.packs || [];
  return <div className="vocabulary-shell" hidden={!visible}>
    <div className={ui.pageHeading}><div><h2>Vocabulary</h2><p>The words and ideas the Dataset scene Director draws from. Packs add more; you choose which ones are on.</p></div></div>
    <nav className="vocabulary-sections" aria-label="Vocabulary sections">
      {sections.map((item) => <button key={item.id} className={ui.button} aria-pressed={section === item.id} onClick={() => setSection(item.id)}>{item.title}</button>)}
    </nav>
    <p className="vocabulary-section-intro">{sections.find((item) => item.id === section).help}</p>
    <PackManagerView visible={visible && section === "packs"} state={state} heading={false} />
    <VocabularyExplorer visible={visible && (section === "browse" || section === "test")} mode={section} packs={packs} revision={state.snapshot} />
    <PackCreator visible={visible && section === "create"} packs={packs} onInstalled={state.reload} />
  </div>;
}
