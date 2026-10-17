import { useState } from "react";
import { BookOpen } from "lucide-react";
import { ui } from "../../ui.js";
import { selectedNames } from "../vocabulary/catalog.js";
import VocabularyLibrary from "./VocabularyLibrary.jsx";

/** The Dataset's vocabulary packs: optional material for the scene writer, chosen in the Vocabulary Library. */
export default function DatasetVocabulary({ catalog, selected, onChange, disabled, error }) {
  const [open, setOpen] = useState(false);
  const names = selectedNames(catalog, selected);
  return <section className="pack-picker" aria-label="Vocabulary">
    <div className="pack-picker-heading">
      <h4>Vocabulary</h4>
      <button className={ui.button} type="button" disabled={disabled || !catalog} onClick={() => setOpen(true)}>
        <BookOpen size={15} aria-hidden="true" />Vocabulary Library</button>
    </div>
    {error ? <p className="pack-picker-problem" role="alert">{error}</p>
      : <p className="pack-picker-help">{names.length ? `Selected: ${names.join(", ")}` : "No packs selected: scenes come from your request alone."}</p>}
    {catalog && <VocabularyLibrary open={open} catalog={catalog} selected={selected}
      onApply={(ids) => { onChange(ids); setOpen(false); }} onCancel={() => setOpen(false)} />}
  </section>;
}
