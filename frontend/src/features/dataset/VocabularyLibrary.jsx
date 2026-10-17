import { useEffect, useRef, useState } from "react";
import { Search, X } from "lucide-react";
import { ui } from "../../ui.js";
import { filterPacks, selectedNames, togglePack } from "../vocabulary/catalog.js";

/** The Vocabulary Library: pick the packs the Dataset scene writer may draw on. Changes apply only on Apply. */
export default function VocabularyLibrary({ open, catalog, selected, onApply, onCancel }) {
  const dialog = useRef(null);
  const [chosen, setChosen] = useState(selected);
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("");
  const [previewId, setPreviewId] = useState("");
  useEffect(() => {
    if (open && !dialog.current?.open) {
      setChosen(selected);  // reopening starts from the applied selection; Cancel discards what changed
      dialog.current?.showModal();
    } else if (!open && dialog.current?.open) dialog.current.close();
  }, [open]);  // eslint-disable-line react-hooks/exhaustive-deps -- reset only when the modal opens
  const packs = filterPacks(catalog, query, category);
  const preview = (catalog?.packs || []).find((pack) => pack.id === previewId);
  const names = selectedNames(catalog, chosen);
  return <dialog ref={dialog} className="app-dialog vocabulary-library" aria-labelledby="vocabulary-library-title"
    aria-describedby="vocabulary-library-description" onCancel={(event) => { event.preventDefault(); onCancel(); }}>
    <header className="vocabulary-library-header">
      <div className="min-w-0 flex-1">
        <h2 id="vocabulary-library-title" className="font-display text-lg font-bold">Vocabulary Library</h2>
        <p id="vocabulary-library-description">Select vocabulary packs for scene generation</p>
      </div>
      <button className={ui.iconButton} type="button" aria-label="Close Vocabulary Library" onClick={onCancel}>
        <X size={18} aria-hidden="true" /></button>
    </header>
    <div className="vocabulary-library-filters">
      <label className="vocabulary-library-search"><Search size={14} aria-hidden="true" />
        <input type="search" aria-label="Search vocabulary" placeholder="Search vocabulary..." value={query}
          onChange={(event) => setQuery(event.target.value)} />
      </label>
      <label className={ui.field}><span>Category</span>
        <select className={ui.select} aria-label="Vocabulary category" value={category} onChange={(event) => setCategory(event.target.value)}>
          <option value="">All Categories</option>
          {(catalog?.categories || []).map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
        </select>
      </label>
    </div>
    <div className="vocabulary-library-panes">
      <section aria-label="Available Packs">
        <h3>Available Packs</h3>
        {packs.length ? <ul>{packs.map((pack) => <li key={pack.id} data-preview={pack.id === previewId}>
          <input type="checkbox" aria-label={`Select ${pack.name} (${pack.category})`} checked={chosen.includes(pack.id)}
            onChange={() => setChosen(togglePack(chosen, pack.id))} />
          <button type="button" onClick={() => setPreviewId(pack.id)} aria-label={`Preview ${pack.name} (${pack.category})`}>
            <span>{pack.name}</span><small>{pack.category}</small></button>
        </li>)}</ul> : <p className="vocabulary-library-empty">No packs match.</p>}
      </section>
      <section aria-label="Pack Preview" aria-live="polite">
        <h3>Pack Preview</h3>
        {preview ? <>
          <p className="vocabulary-library-preview-name">{preview.name}</p>
          <p className="vocabulary-library-preview-category">{preview.category}</p>
          <ul>{preview.entries.map((entry) => <li key={entry}>{entry}</li>)}</ul>
        </> : <p className="vocabulary-library-empty">Click a pack to see its entries.</p>}
      </section>
    </div>
    <p className="vocabulary-library-selected" role="status">Selected: {names.length ? names.join(", ") : "none"}</p>
    <footer className="vocabulary-library-actions">
      <button className={ui.button} type="button" onClick={onCancel}>Cancel</button>
      <button className={ui.primaryButton} type="button" onClick={() => onApply(chosen)}>Apply</button>
    </footer>
  </dialog>;
}
