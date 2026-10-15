import { ArrowLeft, BookOpen, ChevronRight, Search } from "lucide-react";
import { useRef, useState } from "react";
import { ui } from "../../ui.js";
import { packKey, useVocabularyExplorer } from "./useVocabularyExplorer.js";

const label = (text) => text.replaceAll("_", " ").replace(/^./, (letter) => letter.toUpperCase());
const componentLabels = { capability: "Capability implications", body: "Body resources and capabilities",
  participants: "Participant slots", requirements: "Requirements and constraints", spatial: "Spatial relationships",
  claims: "Resource usage", object: "Object capabilities", environment: "Environment capabilities" };

function Reference({ reference, onNavigate }) {
  return reference.exists ? <button type="button" className="vocabulary-reference" onClick={() => onNavigate(reference)}
    title={reference.id}>{reference.name}<ChevronRight size={12} aria-hidden="true" /></button>
    : <span className="vocabulary-missing">{reference.id} (missing or unavailable)</span>;
}

function Fields({ value, references, onNavigate }) {
  if (Array.isArray(value)) return value.length ? <ul className="vocabulary-values">{value.map((item, index) =>
    <li key={index}><Fields value={item} references={references} onNavigate={onNavigate} /></li>)}</ul> : <span className="text-muted">None declared</span>;
  if (value !== null && typeof value === "object") return Object.keys(value).length ? <dl className="vocabulary-fields">
    {Object.entries(value).map(([key, item]) => <div key={key}><dt>{label(key)}</dt><dd>
      <Fields value={item} references={references} onNavigate={onNavigate} /></dd></div>)}</dl> : <span className="text-muted">No additional fields</span>;
  const ref = references.find((item) => item.id === value);
  return ref ? <Reference reference={ref} onNavigate={onNavigate} /> : <span>{typeof value === "boolean" ? String(value) : value}</span>;
}

export function EntryDetails({ detail, onNavigate, onBack }) {
  const { declared, resolved, pack, references, problems } = detail;
  const shown = resolved || declared;
  const keys = Object.keys({ ...declared.components, ...resolved?.components });
  return <article className="vocabulary-entry-detail" aria-label="Entry details">
    <button className={ui.textButton} onClick={onBack}><ArrowLeft size={14} />Back to entries</button>
    <header><div><h3>{declared.name}</h3><p className="vocabulary-entry-id">{declared.id}</p></div>
      <span className="vocabulary-rating" data-rating={shown.rating || pack.rating}>{label(shown.rating || pack.rating)}</span></header>
    <p className="vocabulary-owner">Owned by {pack.name} · {pack.enabled ? "Pack enabled" : "Pack disabled; browsing only"}</p>
    <p>{shown.description || "No description declared."}{!declared.description && resolved?.description && <small> Inherited description</small>}</p>
    <dl className="vocabulary-metadata"><div><dt>Category</dt><dd>{declared.category}</dd></div>
      <div><dt>Content rating source</dt><dd>{resolved && resolved.rating !== (declared.rating || pack.rating) ? "Stricter inherited rating" : declared.rating ? "Entry declaration" : "Pack default"}</dd></div></dl>
    {["aliases", "tags", "notes"].map((field) => <section className="vocabulary-detail-section" key={field}>
      <h4>{label(field)}</h4>{shown[field]?.length ? <ul className="vocabulary-values">{shown[field].map((item, index) =>
        <li key={index}>{item} <small>{declared[field]?.includes(item) ? "Declared" : "Inherited"}</small></li>)}</ul> : <p className="text-muted">None declared</p>}
    </section>)}
    {!!problems.length && <div className="vocabulary-pack-problems" role="alert"><strong>Resolution unavailable</strong>
      <ul>{problems.map((problem, index) => <li key={index}>{problem}</li>)}</ul><p>Only validated declarations are shown. Missing information is not inferred.</p></div>}
    <section className="vocabulary-detail-section"><h4>Inheritance and references</h4>
      {references.length ? <ul className="vocabulary-reference-list">{references.map((reference) => <li key={`${reference.kind}-${reference.id}`}>
        <span><small>{reference.kind === "extends" ? "Inherits from" : label(reference.kind)}</small><Reference reference={reference} onNavigate={onNavigate} /></span>
        <small>{reference.declared ? "Declared reference" : "Inherited reference"} · {reference.pack}</small>
      </li>)}</ul> : <p className="text-muted">No schema references declared.</p>}
    </section>
    <section className="vocabulary-detail-section"><h4>Technical details</h4>
      <p className="text-muted">Resolved values come from this pack and its dependencies, even if disabled. This does not change availability or prove physical feasibility.</p>
      {keys.length ? keys.map((key) => <details className="vocabulary-technical" key={key}>
        <summary>{componentLabels[key] || label(key)}</summary>
        <div className="vocabulary-definition-columns"><section><h5>Declared by this entry</h5>
          {declared.components[key] ? <Fields value={declared.components[key]} references={references} onNavigate={onNavigate} /> : <p className="text-muted">Not declared here</p>}</section>
          {resolved && <section><h5>Resolved including inheritance</h5><Fields value={resolved.components[key]} references={references} onNavigate={onNavigate} /></section>}
        </div></details>) : <p className="text-muted">No component fields declared.</p>}
    </section>
  </article>;
}

const stateLabels = { open: "Open", closed: "Closed", "not reached": "Not reached" };
const stateHints = { open: "ideas are offered here", closed: "the request already decides this", "not reached": "the request doesn't touch this" };
const scopeLabels = { category: "Category wording", arrangement: "Open arrangement", setting: "Open place", theme: "Pack theme", content: "Content level (ranks only)" };
const statusLabels = { feasible: "Fits the cast", eligible: "Compatible", unknown: "Unknown fit" };
const statusHints = { feasible: "Every declared requirement checks out for these characters.",
  eligible: "Nothing declared rules it out for these characters.",
  unknown: "The engine can't tell if it fits, usually because a character matches no body entry." };
const plural = (count, word) => `${count} ${word}${count === 1 ? "" : "s"}`;

function hint(warning) {
  if (/no vocabulary body matches/.test(warning))
    return "Describe characters with words a body entry knows, such as man, woman or person, or a pack body like elf or dragon.";
  if (/no relevant vocabulary/.test(warning))
    return "Name a position, action, place or item, or list what may vary (for example: positions, location) under brief details.";
  return "";
}

function Status({ status }) {
  return <span className="vocabulary-status" data-status={status} title={statusHints[status]}>{statusLabels[status] || label(status)}</span>;
}

function Chip({ item, named }) {
  return <span className="vocabulary-chip" data-source={named ? "direct" : "inspiration"} title={`${item.category} · ${item.pack}`}>
    <small>{item.categoryName}</small>{item.name}</span>;
}

function Matches({ items, names, target, onNavigate }) {
  return <ul className="vocabulary-retrieval-matches">{items.map((item) => <li key={item.id}>
    <div className="vocabulary-match-heading"><Reference reference={target(item)} onNavigate={onNavigate} />
      <span className="vocabulary-match-badges"><Status status={item.status} />
        <span className="vocabulary-rating" data-rating={item.rating}>{label(item.rating)}</span>
        <span className="vocabulary-source" data-source={item.source || "direct"}>{item.source === "inspiration" ? "Idea" : "Named"}</span></span></div>
    {item.description && <p className="vocabulary-match-description">{item.description}</p>}
    {!!item.attach_to?.length && <p className="vocabulary-match-note"><strong>Offered only with</strong> {item.attach_to.map((id) => names[id] || id).join(", ")}</p>}
    {item.warnings.map((warning, index) => <p className="vocabulary-match-warning" key={index}>{warning}</p>)}
    <details className="vocabulary-match-more"><summary>Why it was picked</summary>
      <ul className="vocabulary-match-why">{item.why.map((why, index) => <li key={index}>{why}</li>)}</ul>
      {!!item.needs.length && <p className="vocabulary-match-note"><strong>Needs</strong> {item.needs.join("; ")}</p>}
      {item.note && <p className="vocabulary-match-note">{item.note}</p>}
      <p className="text-muted">{item.pack} · {item.category} · score {item.score}</p>
      {item.binding && <Fields value={{ binding: item.binding, checked_with: item.checked_with }} references={[]} onNavigate={onNavigate} />}</details>
  </li>)}</ul>;
}

function Grouped({ items, categoryName, ...props }) {
  const groups = [...new Set(items.map((item) => item.category))];
  return groups.map((category) => <section className="vocabulary-match-group" key={category}>
    <h5>{categoryName(category)} <small>{items.filter((item) => item.category === category).length}</small></h5>
    <Matches items={items.filter((item) => item.category === category)} {...props} /></section>);
}

function Intent({ intent }) {
  if (!intent?.categories) return null;
  const fixed = Object.entries(intent.fixed || {}), ruledOut = Object.entries(intent.ruled_out || {});
  return <section className="vocabulary-intent" aria-label="Detected intent"><h4>How the request was read</h4>
    <p className="vocabulary-section-help">Detected intent: which categories the request opens for ideas, and which it already decides. To get ideas from a category that isn’t reached, name it under What may vary (for example: acts, toys, outfits).</p>
    <dl className="vocabulary-intent-facts">
      <div><dt>Content level</dt><dd>{intent.content ? label(intent.content) : "Not requested"}</dd></div>
      <div><dt>Pack themes</dt><dd>{intent.themes.length ? intent.themes.map((theme) => `${theme.name} (${theme.why})`).join("; ") : "None"}</dd></div>
      {!!fixed.length && <div><dt>Fixed by the request</dt><dd>{fixed.map(([group, names]) => `${group}: ${names.join(", ")}`).join("; ")}</dd></div>}
      {!!ruledOut.length && <div><dt>Ruled out by the request</dt><dd>{ruledOut.map(([key, words]) => `${key} (${words.join(", ")})`).join("; ")}</dd></div>}
    </dl>
    <ul className="vocabulary-intent-categories">{intent.categories.map((category) => <li key={category.id} data-state={category.state}>
      <div><strong>{category.name}</strong><span className="vocabulary-state" data-state={category.state} title={stateHints[category.state]}>{stateLabels[category.state] || category.state}</span>
        {category.state === "open" && <small>{plural(category.ideas.length, "idea")}</small>}</div>
      {!!category.reached.length && <ul>{category.reached.map((item, index) =>
        <li key={index}>{scopeLabels[item.scope] || item.scope}: {item.why}</li>)}</ul>}
      {category.state === "not reached" ? <p className="text-muted">{category.reason}</p>
        : category.empty && <p className="text-muted">{category.empty}</p>}
    </li>)}</ul>
  </section>;
}

export function RetrievalResults({ result, onNavigate, packs }) {
  function target(item) {
    const pack = packs.find((pack) => pack.id === (item.pack || item.id.split(":")[0]) && pack.valid);
    return { ...item, origin: pack?.origin, exists: !!pack, name: item.name || item.id };
  }
  const ideas = result.inspiration || [];
  const categoryNames = Object.fromEntries((result.intent?.categories || []).map((category) => [category.id, category.name]));
  const categoryName = (id) => categoryNames[id] || label(id || "other");
  const known = Object.fromEntries([...result.entries, ...ideas].map((item) => [item.id, { ...item, categoryName: categoryName(item.category) }]));
  const names = Object.fromEntries(Object.values(known).map((item) => [item.id, item.name]));
  const scenes = (result.scenes || []).filter((scene) => scene.entries.length || scene.ideas.length);
  const chip = (id, named) => <li key={id}>{known[id] ? <Chip item={known[id]} named={named} /> : <span className="vocabulary-chip">{id}</span>}</li>;
  const offered = result.entries.length + ideas.length;
  return <div className="vocabulary-retrieval-results" aria-label="Retrieval results">
    <header className="vocabulary-results-summary">
      <h4>What the Director gets</h4>
      <ul className="vocabulary-stats">
        <li><strong>{result.entries.length}</strong><span>named by the request</span></li>
        <li><strong>{ideas.length}</strong><span>{ideas.length === 1 ? "idea" : "ideas"}</span></li>
        <li><strong>{scenes.length}</strong><span>{scenes.length === 1 ? "scene with suggestions" : "scenes with suggestions"}</span></li>
      </ul>
      <p className="text-muted"><strong>{result.nsfw ? "General, Mature and Adult ratings allowed" : "General and Mature ratings allowed"}.</strong> Named entries are what the request asks for. Ideas are optional: the Director may use or ignore them. Engine statuses describe declared compatibility, not content approval or proof of physical feasibility.</p>
    </header>
    {result.warnings.map((warning, index) => <div className="vocabulary-pack-problems" key={index}><p>{warning}</p>
      {hint(warning) && <p className="vocabulary-hint">Try: {hint(warning)}</p>}</div>)}
    {!offered && !result.warnings.length && <p className="vocabulary-pack-problems">Nothing would be offered. {hint("no relevant vocabulary")}</p>}
    {!!scenes.length && <section className="vocabulary-rotation" aria-label="Per-scene suggestions">
      <h4>Per-scene suggestions (seed {result.seed ?? 0})</h4>
      <p className="vocabulary-section-help">What each Dataset image is offered. Another seed rotates the ideas.
        <span className="vocabulary-legend"><span className="vocabulary-chip" data-source="direct">Named</span><span className="vocabulary-chip" data-source="inspiration">Idea</span></span></p>
      <ol className="vocabulary-scenes">{scenes.map((scene) => <li key={scene.scene} aria-label={`Scene ${scene.scene}: ${[...scene.entries, ...scene.ideas].map((id) => names[id] || id).join("; ")}`}>
        <h5>Scene {scene.scene}</h5><ul>{scene.entries.map((id) => chip(id, true))}{scene.ideas.map((id) => chip(id, false))}</ul></li>)}</ol>
    </section>}
    <section className="vocabulary-results-section"><h4>Named by the request</h4>
      {result.entries.length ? <Grouped items={result.entries} categoryName={categoryName} names={names} target={target} onNavigate={onNavigate} />
        : <p className="text-muted">No entries retrieved for this sample. The request names no specific entry; any suggestions come from ideas.</p>}</section>
    {!!ideas.length && <section className="vocabulary-results-section"><h4>Ideas (optional inspiration)</h4>
      <Grouped items={ideas} categoryName={categoryName} names={names} target={target} onNavigate={onNavigate} /></section>}
    <Intent intent={result.intent} />
    <div className="vocabulary-results-more">
      {!!result.cast.length && <details><summary>Cast inferred by the engine</summary><Fields value={result.cast} references={[]} onNavigate={onNavigate} /></details>}
      {[ ["Excluded", result.excluded, "reason"], ["Suppressed", result.suppressed, "because"] ].map(([title, items, reason]) =>
        !!items.length && <details key={title}><summary>{title} ({items.length})</summary><ul className="vocabulary-reference-list">
          {items.map((item, index) => <li key={index}><Reference reference={target(item)} onNavigate={onNavigate} /><p>{item[reason]}</p></li>)}</ul></details>)}
    </div>
  </div>;
}

const examples = [
  { title: "Two men, positions vary", sample: { request: "2 men having sex", characters: "adult man\nadult man", nsfw: true, randomized: "sex positions, location", avoid: "" } },
  { title: "A fantasy scene", sample: { request: "A dragon resting on a cliff", characters: "", nsfw: false, randomized: "", avoid: "" } },
  { title: "Couple, no toys", sample: { request: "A couple in bed", characters: "adult woman\nadult man", nsfw: true, randomized: "positions", avoid: "no toys" } },
];

function RequestTester({ state, packs, openEntry }) {
  const { sample, editSample, result, inspecting, inspectionError, inspect, detail, detailLoading, detailError, clearEntry, reload, entry } = state;
  const [shown, setShown] = useState({ cast: false, brief: false });
  const toggle = (key) => (event) => { const open = event.currentTarget.open; setShown((current) => current[key] === open ? current : { ...current, [key]: open }); };
  function applyExample(example) {
    editSample({ ...example, seed: sample.seed });
    setShown({ cast: !!example.characters, brief: !!(example.randomized || example.avoid) });
  }
  return <section className="vocabulary-retrieval" aria-label="Retrieval inspection">
    <div className="vocabulary-tester-intro"><div><h3>Test a request</h3>
      <p>Type a request like you would in Dataset and see which vocabulary the scene Director would be offered. Uses only enabled packs. No LLM, scene generation or saved changes.</p></div>
      <div className="vocabulary-examples" aria-label="Example requests"><span>Examples</span>
        {examples.map((example) => <button type="button" className={ui.textButton} key={example.title} onClick={() => applyExample(example.sample)}>{example.title}</button>)}</div></div>
    <form onSubmit={(event) => { event.preventDefault(); inspect(); }}>
      <label className={ui.field}><span>Request</span><textarea className="control textarea" aria-label="Vocabulary sample request"
        value={sample.request} maxLength={4000} rows={3} onChange={(event) => editSample({ request: event.target.value })} placeholder="A dragon resting on a cliff" required /></label>
      <details open={shown.cast} onToggle={toggle("cast")}><summary>Optional character descriptions</summary><p className="vocabulary-section-help">One character per line, e.g. “adult man”, “adult woman”, “elf”. Without characters, whether an entry fits stays unknown.</p>
        <textarea className="control textarea" aria-label="Inspection characters" value={sample.characters} maxLength={8192} rows={2}
          onChange={(event) => editSample({ characters: event.target.value })} placeholder={"adult man\nadult woman"} /></details>
      <details open={shown.brief} onToggle={toggle("brief")}><summary>Optional brief details</summary><p className="vocabulary-section-help">As in a confirmed Dataset brief: what may vary opens categories for ideas, avoid rules entries out, and the seed rotates ideas across scenes.</p>
        <div className="vocabulary-brief-grid">
          <label className={ui.field}><span>What may vary</span><textarea className="control textarea" aria-label="Inspection randomized" value={sample.randomized ?? ""}
            maxLength={1200} rows={2} onChange={(event) => editSample({ randomized: event.target.value })} placeholder="sex positions, location, lighting" /></label>
          <label className={ui.field}><span>Avoid (one per line)</span><textarea className="control textarea" aria-label="Inspection avoid" value={sample.avoid ?? ""}
            maxLength={4200} rows={2} onChange={(event) => editSample({ avoid: event.target.value })} placeholder="no toys" /></label>
          <label className={ui.field}><span>Seed</span><input className={ui.input} aria-label="Inspection seed" inputMode="numeric" value={sample.seed ?? "0"}
            maxLength={10} onChange={(event) => editSample({ seed: event.target.value.replace(/\D/g, "") })} /></label></div></details>
      <div className="vocabulary-inspection-actions"><label className={ui.toggleRow}>
        <input type="checkbox" className={ui.toggleInput} role="switch" aria-label="Allow Adult rating in inspection" checked={sample.nsfw}
          onChange={(event) => editSample({ nsfw: event.target.checked })} /><span className={ui.switch} /><span className={ui.toggleLabel}>Allow Adult rating</span></label>
        <button className={ui.primaryButton} disabled={inspecting || !sample.request.trim()}><Search size={15} />{inspecting ? "Inspecting…" : "Inspect retrieval"}</button></div>
      <p className="vocabulary-footer">This rating filter is not Dataset content approval. Normal Dataset eligibility checks still apply.</p>
    </form>
    {inspectionError && <div className={ui.message} role="alert">{inspectionError}</div>}
    {entry && <div className="vocabulary-detail-panel" aria-live="polite">{detailLoading ? <p role="status">Loading entry details…</p>
      : detailError ? <div className={ui.message} role="alert"><span>{detailError}</span><button className={ui.button} onClick={reload}>Retry entry</button></div>
        : detail && <EntryDetails detail={detail} onNavigate={openEntry} onBack={clearEntry} />}</div>}
    {result && <RetrievalResults result={result} onNavigate={openEntry} packs={packs} />}
  </section>;
}

export function ExplorerView({ visible, packs, state, mode = "browse" }) {
  const { pack, catalogue, loading, error, filters, filter, selectPack, entry, detail, detailLoading, detailError,
    navigate, clearEntry, reload } = state;
  const panel = useRef(null);
  function openEntry(target) {
    navigate(target);
    panel.current?.scrollIntoView({ block: "start" });
    panel.current?.focus({ preventScroll: true });
  }
  if (mode === "test") return <section className="vocabulary-explorer" hidden={!visible} aria-label="Vocabulary request tester">
    <div ref={panel} tabIndex={-1} /><RequestTester state={state} packs={packs} openEntry={openEntry} /></section>;
  return <section className="vocabulary-explorer" hidden={!visible} aria-label="Vocabulary explorer">
    <div className="vocabulary-explorer-intro"><BookOpen size={20} /><div><h3>Browse the vocabulary</h3>
      <p>Read the definitions behind the scene Director’s choices. Browsing a pack never enables it.</p></div></div>
    <div className="vocabulary-explorer-filters">
      <label className={ui.field}><span>Pack</span><select className={ui.select} aria-label="Explore pack" value={pack ? packKey(pack) : ""}
        onChange={(event) => selectPack(event.target.value)}>{!packs.length && <option value="">No packs available</option>}
        {packs.map((item) => <option key={packKey(item)} value={packKey(item)}>{item.name || item.id} · {item.origin}{!item.enabled ? " · disabled" : ""}{!item.valid ? " · broken" : ""}</option>)}
      </select></label>
      <label className={`${ui.field} vocabulary-entry-search`}><span>Find entries</span><div><Search size={15} aria-hidden="true" />
        <input className={ui.input} aria-label="Search vocabulary entries" maxLength={200} value={filters.q}
          onChange={(event) => filter({ q: event.target.value })} placeholder="Name, ID, alias or tag" /></div></label>
      <label className={ui.field}><span>Category</span><select className={ui.select} aria-label="Filter entry category" value={filters.category} onChange={(event) => filter({ category: event.target.value })}>
        <option value="">All categories</option>{catalogue?.categories.map((item) => <option value={item.id} key={item.id}>{item.name} ({item.count})</option>)}</select></label>
      <label className={ui.field}><span>Rating</span><select className={ui.select} aria-label="Filter entry rating" value={filters.rating} onChange={(event) => filter({ rating: event.target.value })}>
        <option value="">All ratings</option>{catalogue?.ratings.map((rating) => <option key={rating} value={rating}>{label(rating)}</option>)}</select></label>
      <label className={ui.field}><span>Sort</span><select className={ui.select} aria-label="Sort vocabulary entries" value={filters.sort} onChange={(event) => filter({ sort: event.target.value })}>
        {Object.entries(catalogue?.sorts || { name: "Name" }).map(([key, title]) => <option value={key} key={key}>{title}</option>)}</select></label>
    </div>
    {pack && !pack.enabled && <p className="vocabulary-guidance">This pack is disabled. Its entries are visible here but unavailable to Dataset retrieval.</p>}
    {loading && <p role="status">Loading entries…</p>}
    {error && <div className={ui.message} role="alert"><span>{error}</span><button className={ui.button} onClick={reload}>Retry explorer</button></div>}
    {!!catalogue?.problems.length && <div className="vocabulary-pack-problems" role="alert"><strong>Pack resolution needs attention</strong><ul>
      {catalogue.problems.map((problem, index) => <li key={index}>{problem}</li>)}</ul></div>}
    <div className="vocabulary-explorer-grid">
      <div className="vocabulary-entry-list" aria-label="Vocabulary entries" aria-busy={loading}>
        {catalogue && !loading && !error && <><p className="vocabulary-entry-count">{catalogue.matched} of {catalogue.total} entries</p>
          {catalogue.categories.map((category) => {
            const entries = catalogue.entries.filter((item) => item.category === category.id);
            return !!entries.length && <section key={category.id}><h4>{category.name} <small>{entries.length}</small></h4>
              <ul>{entries.map((item) => <li key={item.id}><button className="vocabulary-entry-choice" aria-pressed={entry?.id === item.id}
                onClick={() => openEntry({ id: item.id, origin: pack.origin })}>
                <span><strong>{item.name}</strong><small>{item.id}</small></span><span className="vocabulary-rating" data-rating={item.rating}>{label(item.rating)}</span>
              </button></li>)}</ul></section>;
          })}
          {!catalogue.entries.length && <p>No entries match these filters.</p>}
        </>}
        {!packs.length && <p>No packs available. Refresh the Pack Manager to check installation.</p>}
      </div>
      <div ref={panel} className="vocabulary-detail-panel" aria-live="polite" tabIndex={-1}>
        {detailLoading ? <p role="status">Loading entry details…</p> : detailError ? <div className={ui.message} role="alert"><span>{detailError}</span>
          <button className={ui.button} onClick={reload}>Retry entry</button></div> : detail ? <EntryDetails detail={detail} onNavigate={openEntry} onBack={clearEntry} />
            : <div className="vocabulary-detail-placeholder"><BookOpen size={30} /><h3>Start with an entry</h3><p>Select a definition to inspect its requirements, inheritance and references.</p></div>}
      </div>
    </div>
  </section>;
}

export default function VocabularyExplorer({ visible, packs, revision, mode }) {
  const state = useVocabularyExplorer({ visible, packs, revision });
  return <ExplorerView visible={visible} packs={packs} state={state} mode={mode} />;
}
