import { useEffect, useRef, useState } from "react";
import { ChevronDown, Download, LoaderCircle, X } from "lucide-react";
import { ui } from "../../ui.js";
import { canConfirmDatasetReview, datasetCharacterLines, datasetReviewQuestions, datasetUnderstandingSections, datasetUnderstandingSummary } from "./datasetState.js";
import { identityLabels } from "./options.js";

function SummaryList({ label, items, annotations }) {
  if (!items?.length) return null;
  return <div className="dataset-review-list"><h3>{label}</h3>
    <ul>
      {items.map((item, index) => <li className="wrap-anywhere" key={index}>{item}
        {!!annotations?.[index]?.length && <small className="block dataset-review-note">Also: {annotations[index].join(" · ")}</small>}
      </li>)}
    </ul></div>;
}

export default function DatasetConfirmationModal({ review, busy, onRevise, onConfirm, onCancel, onExport }) {
  const dialog = useRef(null);
  const [additions, setAdditions] = useState("");
  useEffect(() => {
    if (review && !dialog.current?.open) dialog.current?.showModal();
    else if (!review && dialog.current?.open) dialog.current.close();
  }, [review]);
  const brief = review?.brief;
  const summary = datasetUnderstandingSummary(brief);
  const working = ["analyzing", "confirming"].includes(review?.status);
  const canConfirm = canConfirmDatasetReview(review, busy, additions);
  const confirmLabel = review?.operation === "dataset/scenes" ? "Confirm and generate scenes"
    : review?.options?.resume ? "Confirm and continue" : "Confirm and generate prompts";
  return <dialog ref={dialog} className="app-dialog dataset-confirmation-dialog"
    aria-labelledby="dataset-confirmation-title" aria-describedby="dataset-confirmation-description"
    onCancel={(event) => { event.preventDefault(); if (review?.status !== "confirming") onCancel(); }}>
    <header className="dataset-review-header">
      <div className="min-w-0 flex-1">
        <h2 id="dataset-confirmation-title" className="font-display text-lg font-bold">Review your Dataset request</h2>
        <p id="dataset-confirmation-description">Check the interpretation, add corrections if needed, then confirm.</p>
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
        <SummaryList label="Characters" items={datasetCharacterLines(brief)} />
      </section>
      <div className="dataset-review-grid">
        <section aria-label="What stays consistent">
          <h3>What stays consistent</h3>
          {summary.consistent.length ? <SummaryList label="Required consistency" items={summary.consistent} />
            : <p className="dataset-review-note">Follow the concept and image requirements below.</p>}
        </section>
        <section aria-label="What should vary">
          <h3>What should vary</h3>
          <SummaryList label="May vary" items={summary.mayVary} />
          <SummaryList label="Must vary" items={summary.mustVary} />
          <p className="dataset-review-note">{brief.expansion_freedom}</p>
        </section>
      </div>
      <section className="dataset-review-requirements" aria-label="Image requirements">
        <SummaryList label="Every image should" items={summary.everyImage} />
        <SummaryList label="Scoped requirements" items={summary.scoped} />
        {!summary.everyImage.length && !summary.scoped.length && <>
          <h3>Every image should</h3><p className="dataset-review-note">Follow the concept and consistency rules above.</p>
        </>}
      </section>
      <section className="dataset-review-output" aria-label="Output settings">
        <h3>Output settings</h3>
        <dl>
          <div><dt>Amount</dt><dd>{review.input.amount ? `${review.input.amount} prompts` : "Not specified"}</dd></div>
          <div><dt>Target model</dt><dd>{review.input.target || "Not specified"}</dd></div>
          <div><dt>Prompt length</dt><dd>{review.input.length || "Not specified"}</dd></div>
          <div><dt>Creativity</dt><dd>{review.input.creativity || "Balanced"}</dd></div>
          <div><dt>Style</dt><dd>{review.input.style || "Auto"}</dd></div>
          <div><dt>Trigger text</dt><dd className="whitespace-pre-wrap">{review.input.trigger || "None; planning only"}</dd></div>
        </dl>
      </section>
      {!!datasetReviewQuestions(brief).length && <section className="dataset-review-questions" role="note">
        <SummaryList label="Answer before generating" items={datasetReviewQuestions(brief)} />
      </section>}
    </>}
    {review && <details className="dataset-details dataset-review-details">
      <summary>Show details<ChevronDown size={14} aria-hidden="true" /></summary>
      <p className="mt-3 text-muted">Requirements must be satisfied; preferences may adjust; creative choices remain open. Generated ideas are suggestions, not new requirements. This is an interpretation, not an output check. Unless noted, rules apply to every image.</p>
      <h3 className="mt-4 font-semibold">Original request and current rules</h3>
      <p className="mt-3 whitespace-pre-wrap wrap-anywhere text-muted">{review.input.subject}</p>
      {review.input.constraints && <p className="mt-3 whitespace-pre-wrap wrap-anywhere text-muted">{review.input.constraints}</p>}
      {review.input.source_mode === "guided" && <p className="mt-3 whitespace-pre-wrap wrap-anywhere text-muted">{review.input.inputs}</p>}
      {review.input.source_mode === "library" && <p className="mt-3 text-muted">Scenes come from your prompt library for {review.input.target}, recast with this cast ({review.input.library_extras === "keep" ? "extra roles kept as background" : "extra roles dropped"}).</p>}
      {brief && <>
        <div className="dataset-review-grid mt-4">
          <SummaryList label="Characters and identity" items={[`${brief.character_count ?? "Unspecified / not applicable"}. ${identityLabels[brief.identity_policy]}`]} />
          <SummaryList label="What the dataset will contain" items={[brief.dataset_contents]} />
          {datasetUnderstandingSections(brief).map(({ label, items, annotations }) =>
            <SummaryList key={label} label={label} items={items} annotations={annotations} />)}
        </div>
      </>}
    </details>}
    <label className={`${ui.field} mt-5`}><span>Extra instructions or answers</span>
      <textarea className={ui.notesInput} aria-label="Extra instructions or answers" value={additions}
        maxLength={Math.max(0, 10000 - (review?.input.constraints?.length || 0) - 1)} disabled={working || busy}
        placeholder="Add a correction, missing rule, or answer to a question…"
        onChange={(event) => setAdditions(event.target.value)} />
      <small className="text-muted">Update the summary after edits, then confirm it. Cancel leaves your saved batch unchanged.</small>
    </label>
    </div>
    <footer className="dataset-review-actions">
      <button className={ui.button} type="button" disabled={review?.status === "confirming"} onClick={onCancel}>Cancel</button>
      <button className={ui.button} type="button" disabled={working || busy} onClick={() => {
        onRevise(additions); setAdditions("");
      }}>{review?.status === "failed" ? "Retry analysis" : "Update summary"}</button>
      <button className={ui.primaryButton} type="button" disabled={!canConfirm} onClick={onConfirm}>{confirmLabel}</button>
    </footer>
  </dialog>;
}
