import { useEffect, useRef } from "react";
import { Download, LoaderCircle, X } from "lucide-react";
import { ui } from "../../ui.js";
import { canConfirmDatasetReview } from "./datasetState.js";
import { selectedNames } from "../vocabulary/catalog.js";

// Rebuild (issue 106): the modal shows only the new Understanding brief.
const genderLabel = (person) => person.gender === "custom" ? person.custom : person.gender;

function PeopleBar({ characters }) {
  return <section className="dataset-review-concept" aria-label="People">
    <h3>{characters.length} {characters.length === 1 ? "person" : "people"} per image</h3>
    <ul className="dataset-review-list">
      {characters.map((person, index) => <li className="wrap-anywhere" key={index}>{person.label}: {genderLabel(person)}</li>)}
    </ul>
  </section>;
}

function ReviewList({ title, items }) {
  return <section className="dataset-review-list" aria-label={title}><h3>{title}</h3>
    {items.length ? <ul>{[...new Set(items)].map((text) => <li className="whitespace-pre-wrap wrap-anywhere" key={text}>{text}</li>)}</ul>
      : <p>None specified</p>}
  </section>;
}

function SceneReview({ brief }) {
  return <>
    {brief.path !== "non_character" && <PeopleBar characters={brief.characters} />}
    <div className="dataset-review-requirements">
      <ReviewList title="Stays the same" items={[brief.fixed, ...brief.must].filter(Boolean)} />
      <ReviewList title="Changes per image" items={[brief.randomized].filter(Boolean)} />
      <ReviewList title="Ruled out" items={brief.avoid} />
    </div>
  </>;
}

export default function DatasetConfirmationModal({ review, busy, catalog, directorLabel, onConfirm, onCancel, onExport }) {
  const dialog = useRef(null);
  useEffect(() => {
    if (review && !dialog.current?.open) dialog.current?.showModal();
    else if (!review && dialog.current?.open) dialog.current.close();
  }, [review]);
  const brief = review?.brief;
  const working = ["analyzing", "confirming"].includes(review?.status);
  const confirmed = review?.status === "confirmed";
  const canConfirm = canConfirmDatasetReview(review, busy);
  return <dialog ref={dialog} className="app-dialog dataset-confirmation-dialog"
    aria-labelledby="dataset-confirmation-title" aria-describedby="dataset-confirmation-description"
    onCancel={(event) => { event.preventDefault(); if (review?.status !== "confirming") onCancel(); }}>
    <header className="dataset-review-header">
      <div className="min-w-0 flex-1">
        <h2 id="dataset-confirmation-title" className="font-display text-lg font-bold">Confirm understanding</h2>
        <p id="dataset-confirmation-description">Is this what you meant?</p>
      </div>
      {onExport && <button className={ui.iconButton} type="button" aria-label="Export generation log" title="Export generation log" onClick={onExport}><Download size={18} aria-hidden="true" /></button>}
      <button className={ui.iconButton} type="button" aria-label="Close review" disabled={review?.status === "confirming"}
        onClick={onCancel} autoFocus><X size={18} aria-hidden="true" /></button>
    </header>
    <div className="dataset-review-body">
    {working && <p className="mt-4 flex items-center gap-2 text-xs" role="status"><LoaderCircle size={16} className="dataset-loader" aria-hidden="true" />{review.status === "analyzing" ? "Understanding your request…" : "Confirming…"}</p>}
    {review?.error && <p className={`${ui.warningNote} mt-4`} role="alert">{review.error}</p>}
    {review?.notice && <p className={`${ui.subtleNote} mt-4`} role="status">{review.notice}</p>}
    {brief && <>
      <section className="dataset-review-concept" aria-label="Summary">
        <h3>Summary</h3>
        <p className="whitespace-pre-wrap wrap-anywhere">{brief.summary}</p>
      </section>
      <SceneReview brief={brief} />
      {!!brief.input.guided_inputs?.length && <section className="dataset-review-concept" aria-label="Guided inputs">
        <h3>Guided inputs</h3><ol>{brief.input.guided_inputs.map((item, index) => <li key={index}>{item}</li>)}</ol>
      </section>}
      <section className="dataset-review-list" aria-label="Vocabulary"><h3>Vocabulary</h3>
        {review.input?.vocabulary_packs?.length ? <ul>{selectedNames(catalog, review.input.vocabulary_packs).map((name) =>
          <li className="wrap-anywhere" key={name}>{name}</li>)}</ul> : <p>No packs selected</p>}
      </section>
      <details className="dataset-review-details">
      <summary>Output settings</summary>
      <section className="dataset-review-output" aria-label="Output settings">
        <h3>Output settings</h3>
        <dl>
          <div><dt>Director</dt><dd>{directorLabel || brief.settings.director || "Not specified"}</dd></div>
          <div><dt>Style</dt><dd>{brief.settings.style || "Not specified"}</dd></div>
          <div><dt>Target model</dt><dd>{brief.settings.target || "Not specified"}</dd></div>
        </dl>
      </section>
      </details>
    </>}
    </div>
    <footer className="dataset-review-actions">
      <button className={ui.primaryButton} type="button" disabled={!canConfirm} onClick={onConfirm}>Confirm</button>
      <button className={ui.button} type="button" disabled={review?.status === "confirming"} onClick={onCancel}>{confirmed ? "Close" : "Cancel"}</button>
    </footer>
  </dialog>;
}
