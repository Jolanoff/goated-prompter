import { useEffect, useRef, useState } from "react";
import { ArrowRight, Box, Check, ChevronRight, Cloud, Image, Link, PersonStanding, Plus, Search,
  Shirt, Smile, Sparkles, Sun, Trash2, UserRound, X } from "lucide-react";
import { ui } from "../../ui.js";
import { cleanSelection, filterPacks, togglePack } from "../vocabulary/catalog.js";
import { relatedPacks, sortPacks } from "./vocabularyLibrary.js";
import "./vocabulary-library.css";

const categoryIcons = {
  Subjects: UserRound, "Actions & Poses": PersonStanding, Clothing: Shirt, Expressions: Smile,
  "Mood & Tone": Sparkles, Spaces: Box, "Objects & Props": Image, Lighting: Sun,
  "Camera & Composition": Image, "Effects & Atmosphere": Cloud,
};

function CategoryIcon({ category, size = 16 }) {
  const Icon = categoryIcons[category] || Box;
  return <Icon size={size} aria-hidden="true" />;
}

function CategoryBadge({ category }) {
  return <span className="vocabulary-library-badge"><CategoryIcon category={category} /><span>{category}</span></span>;
}

/** Selection is staged locally until Apply; closing the dialog discards it. */
export default function VocabularyLibrary({ open, catalog, selected, onApply, onCancel }) {
  const dialog = useRef(null);
  const search = useRef(null);
  const previewPanel = useRef(null);
  const [chosen, setChosen] = useState([]);
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("");
  const [sort, setSort] = useState("name");
  const [previewId, setPreviewId] = useState("");
  const [expandedId, setExpandedId] = useState("");
  useEffect(() => {
    if (open && !dialog.current?.open) {
      const selection = cleanSelection(catalog, selected);
      setChosen(selection);
      setQuery("");
      setCategory("");
      setSort("name");
      setPreviewId(selection[0] || "");
      setExpandedId("");
      dialog.current?.showModal();
      search.current?.focus();
    } else if (!open && dialog.current?.open) dialog.current.close();
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps -- staged state resets only on opening

  const allPacks = catalog?.packs || [];
  const packs = sortPacks(filterPacks(catalog, query, category), sort);
  const preview = packs.find((pack) => pack.id === previewId) || packs[0];
  const selection = cleanSelection(catalog, chosen);
  const selectedPacks = selection.map((id) => allPacks.find((pack) => pack.id === id));
  const related = relatedPacks(allPacks, preview);
  const expanded = !!preview && expandedId === preview.id;
  const entries = preview ? preview.entries.slice(0, expanded ? undefined : 12) : [];
  useEffect(() => {
    previewPanel.current?.scrollTo({ top: 0 });
  }, [preview?.id]);

  function previewPack(pack) {
    setPreviewId(pack.id);
    setExpandedId("");
  }
  function toggle(pack) {
    setChosen((ids) => togglePack(ids, pack.id));
  }
  function resetFilters() {
    setQuery("");
    setCategory("");
  }

  return <dialog ref={dialog} className="app-dialog vocabulary-library" aria-labelledby="vocabulary-library-title"
    aria-describedby="vocabulary-library-description" onCancel={(event) => { event.preventDefault(); onCancel(); }}>
    <header className="vocabulary-library-header">
      <div>
        <h2 id="vocabulary-library-title">Vocabulary Library</h2>
        <p id="vocabulary-library-description">Select vocabulary packs for scene generation</p>
      </div>
      <button className={ui.iconButton} type="button" aria-label="Close Vocabulary Library" onClick={onCancel}>
        <X size={24} aria-hidden="true" /></button>
    </header>
    <div className="vocabulary-library-filters">
      <label className="vocabulary-library-search"><Search size={20} aria-hidden="true" />
        <input ref={search} type="search" aria-label="Search vocabulary" placeholder="Search vocabulary packs..." value={query}
          onChange={(event) => setQuery(event.target.value)} />
      </label>
      <div className="vocabulary-library-categories" role="group" aria-label="Vocabulary category">
        <button type="button" aria-pressed={!category} onClick={() => setCategory("")}>All</button>
        {(catalog?.categories || []).map((item) => <button type="button" key={item.id} aria-pressed={category === item.id}
          onClick={() => setCategory(item.id)}><CategoryIcon category={item.id} size={19} />{item.name}</button>)}
      </div>
    </div>
    <div className="vocabulary-library-panes">
      <section className="vocabulary-library-browser" aria-label="Available Packs">
        <div className="vocabulary-library-list-heading">
          <h3>Vocabulary Packs ({packs.length})</h3>
          <label className="vocabulary-library-sort">Sort by:
            <select aria-label="Sort vocabulary packs" value={sort} onChange={(event) => setSort(event.target.value)}>
              <option value="name">Name</option><option value="category">Category</option><option value="entries">Entries</option>
            </select>
          </label>
        </div>
        {packs.length ? <ul className="vocabulary-library-list">{packs.map((pack) => <li key={pack.id}
          data-preview={pack.id === preview?.id}>
          <input type="checkbox" aria-label={`Select ${pack.name} (${pack.category})`} checked={selection.includes(pack.id)}
            onChange={() => { toggle(pack); previewPack(pack); }} />
          <button className="vocabulary-library-pack-open" type="button" onClick={() => previewPack(pack)}
            aria-pressed={pack.id === preview?.id} aria-label={`Preview ${pack.name} (${pack.category})`}>
            <span className="vocabulary-library-pack-name">{pack.name}</span><CategoryBadge category={pack.category} />
            <small>{pack.entries.length} {pack.entries.length === 1 ? "entry" : "entries"}</small>
            <ChevronRight size={16} aria-hidden="true" />
          </button>
        </li>)}</ul> : <div className="vocabulary-library-empty">
          <p>No packs match your search.</p><button className={ui.textButton} type="button" onClick={resetFilters}>Reset filters</button>
        </div>}
      </section>
      <section ref={previewPanel} className="vocabulary-library-preview" aria-label="Pack Preview">
        {preview ? <>
          <div className="vocabulary-library-preview-heading">
            <span className="vocabulary-library-category-tile"><CategoryIcon category={preview.category} size={34} /></span>
            <div className="vocabulary-library-preview-info">
              <div className="vocabulary-library-preview-title"><h3>{preview.name}</h3><CategoryBadge category={preview.category} />
                <small>{preview.entries.length} entries</small></div>
              <p className="vocabulary-library-preview-description">{preview.description || `Vocabulary choices from ${preview.category}.`}</p>
              {preview.source === "imported" && <small className="vocabulary-library-source">Imported pack</small>}
            </div>
          </div>
          <div className="vocabulary-library-samples">
            <div className="vocabulary-library-section-heading"><h4>Sample Entries</h4>
              <span>Showing {entries.length} of {preview.entries.length}</span></div>
            <ul className="vocabulary-library-entry-list" data-expanded={expanded}>{entries.map((entry) =>
              <li key={entry} title={expanded ? undefined : entry}><span>{entry}</span></li>)}</ul>
            {preview.entries.length > 12 && <button className={`${ui.textButton} vocabulary-library-expand`} type="button"
              aria-expanded={expanded} onClick={() => setExpandedId(expanded ? "" : preview.id)}>
              {expanded ? "Show fewer entries" : "Show all entries"}</button>}
          </div>
          <div className="vocabulary-library-related">
            <div className="vocabulary-library-section-heading"><h4><Link size={18} aria-hidden="true" />Related Packs</h4>
              <button className={ui.textButton} type="button" aria-label="View all related packs"
                onClick={() => { setQuery(""); setCategory(preview.category); }}>View all <ArrowRight size={15} aria-hidden="true" /></button>
            </div>
            <p>More packs in {preview.category}:</p>
            {related.length ? <ul className="vocabulary-library-related-list">{related.map((pack) => <li key={pack.id}>
              <button className="vocabulary-library-related-open" type="button" aria-label={`Preview related ${pack.name} (${pack.category})`}
                onClick={() => { setQuery(""); previewPack(pack); }}>
                <span className="vocabulary-library-category-tile"><CategoryIcon category={pack.category} size={22} /></span>
                <span><strong>{pack.name}</strong><small>{pack.entries.length} entries</small></span>
              </button>
              <button className={ui.iconButton} type="button" aria-label={`${selection.includes(pack.id) ? "Deselect" : "Select"} ${pack.name} (${pack.category})`}
                aria-pressed={selection.includes(pack.id)} onClick={() => toggle(pack)}>
                {selection.includes(pack.id) ? <Check size={18} aria-hidden="true" /> : <Plus size={18} aria-hidden="true" />}
              </button>
            </li>)}</ul> : <p className="vocabulary-library-empty">No other packs in this category yet.</p>}
          </div>
        </> : <div className="vocabulary-library-empty"><Box size={32} aria-hidden="true" />
          <p>Choose another search or category to find a pack.</p></div>}
      </section>
    </div>
    <footer className="vocabulary-library-footer">
      <div className="vocabulary-library-selection-heading"><h3 aria-live="polite">Selected Packs ({selection.length})</h3>
        <button className={ui.textButton} type="button" disabled={!selection.length} onClick={() => setChosen([])}>
          <Trash2 size={15} aria-hidden="true" />Clear all</button></div>
      <div className="vocabulary-library-selection-bottom">
        <ul className="vocabulary-library-selected" aria-label="Selected packs">{selectedPacks.map((pack) => <li key={pack.id}>
          <CategoryIcon category={pack.category} /><span>{pack.name}</span>
          <button type="button" aria-label={`Remove ${pack.name} (${pack.category})`} onClick={() => toggle(pack)}>
            <X size={14} aria-hidden="true" /></button></li>)}</ul>
        {!selection.length && <p className="vocabulary-library-selection-empty">No packs selected. Scenes will follow your request alone.</p>}
        <div className="vocabulary-library-actions">
          <button className={ui.button} type="button" onClick={onCancel}>Cancel</button>
          <button className={ui.primaryButton} type="button" onClick={() => onApply(selection)}>Apply ({selection.length})</button>
        </div>
      </div>
    </footer>
  </dialog>;
}
