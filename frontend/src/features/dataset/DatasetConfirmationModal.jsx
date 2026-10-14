import { useEffect, useRef, useState } from "react";
import { Download, LoaderCircle, X } from "lucide-react";
import { ui } from "../../ui.js";
import { canConfirmDatasetReview, datasetCharacterLines, datasetReviewQuestions, datasetUnderstandingSections } from "./datasetState.js";
import { identityLabels } from "./options.js";

function SummaryList({ label, items }) {
  if (!items?.length) return null;
  return <div className="dataset-review-list"><h3>{label}</h3>
    <ul>
      {items.map((item, index) => <li className="wrap-anywhere" key={index}>{item}</li>)}
    </ul></div>;
}

export default function DatasetConfirmationModal({ review, busy, onRevise, onConfirm, onCancel, onExport }) {
  const dialog = useRef(null);
  const [additions, setAdditions] = useState("");
  useEffect(() => {
    if (review && !dialog.current?.open) dialog.current?.showModal();
    else if (!review && dialog.current?.open) dialog.current.close();
  }, [review]);
  const brief = review?.summary || review?.brief;
  const working = ["analyzing", "confirming"].includes(review?.status);
  const canConfirm = canConfirmDatasetReview(review, busy, additions);
  const confirmLabel = review?.options?.resume ? "Confirm & Continue" : "Confirm & Generate";
  return <dialog ref={dialog} className="app-dialog dataset-confirmation-dialog"
    aria-labelledby="dataset-confirmation-title" aria-describedby="dataset-confirmation-description"
    onCancel={(event) => { event.preventDefault(); if (review?.status !== "confirming") onCancel(); }}>
    <header className="dataset-review-header">
      <div className="min-w-0 flex-1">
        <h2 id="dataset-confirmation-title" className="font-display text-lg font-bold">Confirm understanding</h2>
        <p id="dataset-confirmation-description">Is this what you meant? Scenes are planned only after you confirm.</p>
      </div>
      {onExport && <button className={ui.iconButton} type="button" aria-label="Export generation log" title="Export generation log" onClick={onExport}><Download size={18} aria-hidden="true" /></button>}
      <button className={ui.iconButton} type="button" aria-label="Cancel request review" disabled={review?.status === "confirming"}
        onClick={onCancel} autoFocus><X size={18} aria-hidden="true" /></button>
    </header>
    <div className="dataset-review-body">
    {working && <p className="mt-4 flex items-center gap-2 text-xs" role="status"><LoaderCircle size={16} className="dataset-loader" aria-hidden="true" />{review.status === "analyzing" ? "Understanding your request…" : "Starting confirmed generation…"}</p>}
    {review?.error && <p className={`${ui.warningNote} mt-4`} role="alert">{review.error}</p>}
    {review?.notice && <p className={`${ui.subtleNote} mt-4`}>{review.notice}</p>}
    {brief && <>
      <section className="dataset-review-concept" aria-label="Concept">
        <h3>Concept</h3>
        <p className="whitespace-pre-wrap wrap-anywhere">{brief.requested_generation}</p>
        <p className="dataset-review-identity">{brief.character_count != null && `${brief.character_count} characters per image. `}{identityLabels[brief.identity_policy]}</p>
        <SummaryList label="Subjects" items={datasetCharacterLines(brief)} />
        <SummaryList label="Requested themes" items={brief.modules?.enabled} />
        <SummaryList label="Excluded themes" items={brief.modules?.excluded} />
      </section>
      <section className="dataset-review-requirements" aria-label="Image requirements">
        {datasetUnderstandingSections(brief).filter(({ items }) => items.length).map(({ label, items }) =>
          <SummaryList key={label} label={label} items={items} />)}
        <p className="dataset-review-note">{brief.expansion_freedom}</p>
      </section>
      <section className="dataset-review-output" aria-label="Output settings">
        <h3>Output settings</h3>
        <dl>
          <div><dt>Amount</dt><dd>{review.input.amount ? `${review.input.amount} prompts` : "Not specified"}</dd></div>
          <div><dt>Target model</dt><dd>{review.input.target || "Not specified"}</dd></div>
          <div><dt>Prompt length</dt><dd>{review.input.length || "Not specified"}</dd></div>
        </dl>
      </section>
      {!!datasetReviewQuestions(brief).length && <section className="dataset-review-questions" role="note">
        <SummaryList label="Answer before generating" items={datasetReviewQuestions(brief)} />
      </section>}
    </>}
    <label className={`${ui.field} mt-5`}><span>Corrections or answers</span>
      <textarea className={ui.notesInput} aria-label="Corrections or answers" value={additions}
        maxLength={Math.max(0, 10000 - (review?.input.constraints?.length || 0) - 1)} disabled={working || busy}
        placeholder="Add a correction, missing rule, or answer to a question…"
        onChange={(event) => setAdditions(event.target.value)} />
      <small className="text-muted">Update understanding after a correction, then confirm. Cancel leaves your saved batch unchanged.</small>
    </label>
    </div>
    <footer className="dataset-review-actions">
      <button className={ui.button} type="button" disabled={working || busy} onClick={() => {
        onRevise(additions); setAdditions("");
      }}>Update understanding</button>
      <button className={ui.primaryButton} type="button" disabled={!canConfirm} onClick={onConfirm}>{confirmLabel}</button>
      <button className={ui.button} type="button" disabled={review?.status === "confirming"} onClick={onCancel}>Cancel</button>
    </footer>
  </dialog>;
}
