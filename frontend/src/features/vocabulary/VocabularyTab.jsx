import { useRef, useState } from "react";
import { Box, ChevronDown, Package, RefreshCw, Upload } from "lucide-react";
import { api } from "../../api.js";
import { ui } from "../../ui.js";
import { packsByCategory } from "./catalog.js";
import { useCatalog } from "./useCatalog.js";

/** Sends each chosen file to the server, which saves it in data/vocabulary/<its category's folder>/. */
export async function importPackFiles(files, send = (body) => api("/vocabulary/import", body)) {
  const results = [];
  for (const file of files) {
    try {
      const data = await send({ filename: file.name, content: await file.text() });
      results.push({ file: file.name, ok: true, pack: data.pack });
    } catch (failure) {
      results.push({ file: file.name, ok: false, error: failure.message });
    }
  }
  return results;
}

function PackCard({ pack }) {
  return <li className="vocabulary-pack">
    <div className="vocabulary-pack-heading">
      <span className="vocabulary-pack-icon" aria-hidden="true"><Box size={18} /></span>
      <div className="vocabulary-pack-title"><h4>{pack.name}</h4><span>{pack.source === "imported" ? "Imported · " : ""}{pack.id}.json</span></div>
    </div>
    {pack.description && <p className="vocabulary-description">{pack.description}</p>}
    <p className="vocabulary-meta">{pack.entries.length} {pack.entries.length === 1 ? "entry" : "entries"}</p>
    <details className="vocabulary-entries">
      <summary>Entries<ChevronDown size={13} aria-hidden="true" /></summary>
      <ul>{pack.entries.map((entry) => <li key={entry}>{entry}</li>)}</ul>
    </details>
  </li>;
}

export default function VocabularyTab({ visible }) {
  const { catalog, error, loading, reload } = useCatalog(visible);
  const input = useRef(null);
  const [importing, setImporting] = useState(false);
  const [imported, setImported] = useState([]);
  async function onFiles(event) {
    const files = [...(event.target.files || [])];
    event.target.value = "";
    if (!files.length) return;
    setImporting(true);
    const results = await importPackFiles(files);
    setImported(results);
    setImporting(false);
    await reload();
  }
  return <section className="vocabulary-view" hidden={!visible} aria-label="Vocabulary" aria-busy={loading}>
    <div className={ui.pageHeading}>
      <div><h2>Vocabulary</h2><p>Packs of optional words for the Dataset scene writer. Select them in the Dataset tab's Vocabulary Library.</p></div>
      <div className="flex flex-wrap gap-2">
        <input ref={input} type="file" accept=".json,application/json" multiple hidden aria-label="Vocabulary pack files"
          onChange={onFiles} />
        <button className={ui.button} disabled={loading || importing} onClick={() => input.current?.click()}>
          <Upload size={15} />{importing ? "Importing…" : "Import packs"}</button>
        <button className={ui.button} disabled={loading} onClick={reload}><RefreshCw size={15} />Refresh</button>
      </div>
    </div>
    <div className="vocabulary-guidance"><Package size={18} aria-hidden="true" />
      <p>Import a pack: choose a JSON file such as
        {" "}<code>{'{"name": "Rooftops", "category": "Spaces", "description": "City rooftops at night", "entries": ["rooftop bar", "water tower"]}'}</code>.
        The description is optional: a short note on what the pack is for and how its entries are written, which the
        scene writer reads with the pack. It is saved in <code>data/vocabulary/</code>, in the folder of its category; importing the same file again replaces it.</p>
    </div>
    {!!imported.length && <ul className="vocabulary-feedback" role="status">{imported.map((row) => <li key={row.file}>
      {row.ok ? `Imported ${row.pack.name} into ${row.pack.category}.` : row.error}</li>)}</ul>}
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
        : <p className="vocabulary-empty">No {category.name} packs yet.</p>}
    </section>)}
  </section>;
}
