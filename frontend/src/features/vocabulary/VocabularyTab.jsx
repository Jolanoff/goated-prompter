import { Box, ChevronDown, Package, RefreshCw } from "lucide-react";
import { ui } from "../../ui.js";
import { packsByCategory } from "./catalog.js";
import { useCatalog } from "./useCatalog.js";

function PackCard({ pack }) {
  return <li className="vocabulary-pack">
    <div className="vocabulary-pack-heading">
      <span className="vocabulary-pack-icon" aria-hidden="true"><Box size={18} /></span>
      <div className="vocabulary-pack-title"><h4>{pack.name}</h4><span>{pack.id}.json</span></div>
    </div>
    <p className="vocabulary-meta">{pack.entries.length} {pack.entries.length === 1 ? "entry" : "entries"}</p>
    <details className="vocabulary-entries">
      <summary>Entries<ChevronDown size={13} aria-hidden="true" /></summary>
      <ul>{pack.entries.map((entry) => <li key={entry}>{entry}</li>)}</ul>
    </details>
  </li>;
}

export default function VocabularyTab({ visible }) {
  const { catalog, error, loading, reload } = useCatalog(visible);
  return <section className="vocabulary-view" hidden={!visible} aria-label="Vocabulary" aria-busy={loading}>
    <div className={ui.pageHeading}>
      <div><h2>Vocabulary</h2><p>Packs of optional words for the Dataset scene writer. Select them in the Dataset tab's Vocabulary Library.</p></div>
      <button className={ui.button} disabled={loading} onClick={reload}><RefreshCw size={15} />Refresh</button>
    </div>
    <div className="vocabulary-guidance"><Package size={18} aria-hidden="true" />
      <p>Add a pack: put one JSON file in its category folder, such as <code>vocabulary/Spaces/Rooftops.json</code> containing
        {" "}<code>{'{"name": "Rooftops", "category": "Spaces", "entries": ["rooftop bar", "water tower"]}'}</code>, then Refresh.</p>
    </div>
    {error && <div className={ui.message} role="alert"><span>{error}</span></div>}
    {loading && <p className="vocabulary-feedback" role="status">Loading vocabulary…</p>}
    {!!catalog?.problems.length && <div className="vocabulary-problems" role="alert">
      <strong>{catalog.problems.length === 1 ? "One file could not be read" : `${catalog.problems.length} files could not be read`}</strong>
      <span>Every other pack still works.</span>
      <ul>{catalog.problems.map((row, index) => <li key={`${row.file}-${index}`}><code>{row.file}</code>: {row.problem}</li>)}</ul>
    </div>}
    {catalog && packsByCategory(catalog).map(({ category, packs }) => <section key={category.id} className="vocabulary-category"
      aria-label={category.name}>
      <h3>{category.name}</h3>
      {category.description && <p className="vocabulary-description">{category.description}</p>}
      {packs.length ? <ul className="vocabulary-packs">{packs.map((pack) => <PackCard key={pack.id} pack={pack} />)}</ul>
        : <p className="vocabulary-empty">No packs in <code>vocabulary/{category.folder}/</code> yet.</p>}
    </section>)}
  </section>;
}
