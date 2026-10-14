import { ArrowLeft, BookOpen, ChevronRight, Search } from "lucide-react";
import { useRef } from "react";
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

export function RetrievalResults({ result, onNavigate, packs }) {
  function target(item) {
    const pack = packs.find((pack) => pack.id === (item.pack || item.id.split(":")[0]) && pack.valid);
    return { ...item, origin: pack?.origin, exists: !!pack, name: item.name || item.id };
  }
  return <div className="vocabulary-retrieval-results" aria-label="Retrieval results">
    <p>{result.entries.length} matches · {result.nsfw ? "General, Mature and Adult ratings allowed" : "General and Mature ratings allowed"}</p>
    <p className="text-muted">Engine statuses describe declared compatibility, not content approval or proof of physical feasibility.</p>
    {result.warnings.map((warning, index) => <p className="vocabulary-pack-problems" key={index}>{warning}</p>)}
    {result.entries.length ? <ul className="vocabulary-retrieval-matches">{result.entries.map((item) => <li key={item.id}>
      <div className="vocabulary-match-heading"><Reference reference={target(item)} onNavigate={onNavigate} />
        <span className="vocabulary-rating" data-rating={item.rating}>{label(item.rating)}</span><strong>{label(item.status)}</strong></div>
      <p className="text-muted">{item.pack} · {item.category} · score {item.score}</p><p>{item.description}</p>
      <ul>{item.why.map((why, index) => <li key={index}>{why}</li>)}</ul>
      {!!item.needs.length && <p>Needs: {item.needs.join("; ")}</p>}
      {item.warnings.map((warning, index) => <p key={index}>{warning}</p>)}
      {item.note && <p>{item.note}</p>}
      {item.binding && <details><summary>Participant binding and checks</summary>
        <Fields value={{ binding: item.binding, checked_with: item.checked_with }} references={[]} onNavigate={onNavigate} /></details>}
    </li>)}</ul> : <p>No entries retrieved for this sample.</p>}
    {!!result.cast.length && <details><summary>Cast inferred by the engine</summary><Fields value={result.cast} references={[]} onNavigate={onNavigate} /></details>}
    {[ ["Excluded", result.excluded, "reason"], ["Suppressed", result.suppressed, "because"] ].map(([title, items, reason]) =>
      !!items.length && <details key={title}><summary>{title} ({items.length})</summary><ul className="vocabulary-reference-list">
        {items.map((item, index) => <li key={index}><Reference reference={target(item)} onNavigate={onNavigate} /><p>{item[reason]}</p></li>)}</ul></details>)}
  </div>;
}

export function ExplorerView({ visible, packs, state }) {
  const { pack, catalogue, loading, error, filters, filter, selectPack, entry, detail, detailLoading, detailError,
    navigate, clearEntry, sample, editSample, result, inspecting, inspectionError, inspect, reload } = state;
  const panel = useRef(null);
  function openEntry(target) {
    navigate(target);
    panel.current?.scrollIntoView({ block: "start" });
    panel.current?.focus({ preventScroll: true });
  }
  return <section className="vocabulary-explorer" hidden={!visible} aria-label="Vocabulary explorer">
    <div className="vocabulary-explorer-intro"><BookOpen size={20} /><div><h3>Explore the vocabulary</h3>
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
    <section className="vocabulary-retrieval" aria-label="Retrieval inspection">
      <h3>Try a sample request</h3><p>Deterministic inspection of enabled packs. No LLM, scene generation or saved changes.</p>
      <form onSubmit={(event) => { event.preventDefault(); inspect(); }}>
        <label className={ui.field}><span>Sample request</span><textarea className="control textarea" aria-label="Vocabulary sample request"
          value={sample.request} maxLength={4000} rows={3} onChange={(event) => editSample({ request: event.target.value })} placeholder="A dragon resting on a cliff" required /></label>
        <details><summary>Optional character descriptions</summary><p>One character per line. Without a declared cast, compatibility may be unknown.</p>
          <textarea className="control textarea" aria-label="Inspection characters" value={sample.characters} maxLength={8192} rows={2}
            onChange={(event) => editSample({ characters: event.target.value })} placeholder="An adult human\nAn adult elf" /></details>
        <div className="vocabulary-inspection-actions"><label className={ui.toggleRow}>
          <input type="checkbox" className={ui.toggleInput} role="switch" aria-label="Allow Adult rating in inspection" checked={sample.nsfw}
            onChange={(event) => editSample({ nsfw: event.target.checked })} /><span className={ui.switch} /><span className={ui.toggleLabel}>Allow Adult rating</span></label>
          <button className={ui.primaryButton} disabled={inspecting || !sample.request.trim()}><Search size={15} />{inspecting ? "Inspecting…" : "Inspect retrieval"}</button></div>
        <p className="vocabulary-footer">This rating filter is not Dataset content approval. Normal Dataset eligibility checks still apply.</p>
      </form>
      {inspectionError && <div className={ui.message} role="alert">{inspectionError}</div>}
      {result && <RetrievalResults result={result} onNavigate={openEntry} packs={packs} />}
    </section>
  </section>;
}

export default function VocabularyExplorer({ visible, packs, revision }) {
  const state = useVocabularyExplorer({ visible, packs, revision });
  return <ExplorerView visible={visible} packs={packs} state={state} />;
}
