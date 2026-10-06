import { useEffect, useRef, useState } from "react";
import { LoaderCircle, X } from "lucide-react";
import { ui } from "../ui.js";
import { canConfirmDatasetReview, datasetReviewQuestions, datasetUnderstandingSections } from "./datasetState.js";

const identityLabels = {
  fixed: "Fixed; preserve the specified identities",
  random_per_prompt: "Randomized per independent prompt; consistent within its idea and scene",
  not_applicable: "No character identity applies",
  mixed: "Mixed identity policies; follow the requirements for each subject and guided input",
};

function SummaryList({ label, items }) {
  if (!items?.length) return null;
  return <div className="mt-4"><h3 className="text-xs font-semibold">{label}</h3>
    <ul className="mt-2 grid gap-2 pl-4 text-xs leading-relaxed text-muted list-disc">
      {items.map((item, index) => <li className="wrap-anywhere" key={index}>{item}</li>)}
    </ul></div>;
}

export default function DatasetConfirmationModal({ review, busy, onRevise, onConfirm, onCancel }) {
  const dialog = useRef(null);
  const [additions, setAdditions] = useState("");
  useEffect(() => {
    if (review && !dialog.current?.open) dialog.current?.showModal();
    else if (!review && dialog.current?.open) dialog.current.close();
  }, [review]);
  const brief = review?.brief;
  const working = ["analyzing", "confirming"].includes(review?.status);
  const canConfirm = canConfirmDatasetReview(review, busy, additions);
  const confirmLabel = review?.operation === "dataset/scenes" ? "Confirm and plan scenes" : "Confirm and generate prompts";
  return <dialog ref={dialog} className="app-dialog dataset-confirmation-dialog"
    aria-labelledby="dataset-confirmation-title" aria-describedby="dataset-confirmation-description"
    onCancel={(event) => { event.preventDefault(); if (review?.status !== "confirming") onCancel(); }}>
    <header className="mb-4 flex items-center gap-3 border-b border-line pb-4">
      <h2 id="dataset-confirmation-title" className="min-w-0 flex-1 font-display text-lg font-bold">Review your Dataset request</h2>
      <button className={ui.iconButton} type="button" aria-label="Cancel request review" disabled={review?.status === "confirming"}
        onClick={onCancel} autoFocus><X size={18} aria-hidden="true" /></button>
    </header>
    <p id="dataset-confirmation-description" className="text-xs leading-relaxed text-muted">Confirm what the engine understood before it creates ideas, scenes or prompts. These are interpreted requirements, not output checks.</p>
    {working && <p className="mt-4 flex items-center gap-2 text-xs" role="status"><LoaderCircle size={16} className="dataset-loader" aria-hidden="true" />{review.status === "analyzing" ? "Understanding your request…" : "Starting confirmed generation…"}</p>}
    {review?.error && <p className={`${ui.warningNote} mt-4`} role="alert">{review.error}</p>}
    {review?.notice && <p className={`${ui.subtleNote} mt-4`}>{review.notice}</p>}
    {brief && <>
      <dl className="mt-5 grid gap-4 text-xs leading-relaxed">
        <div><dt className="font-semibold">What you want</dt><dd className="mt-1 whitespace-pre-wrap wrap-anywhere text-muted">{brief.requested_generation}</dd></div>
        <div><dt className="font-semibold">Characters and identity</dt>
          <dd className="mt-1 text-muted">{brief.character_count ?? "Unspecified / not applicable"}. {identityLabels[brief.identity_policy]}</dd></div>
        <div><dt className="font-semibold">How far the idea may expand</dt><dd className="mt-1 wrap-anywhere text-muted">{brief.expansion_freedom}</dd></div>
        <div><dt className="font-semibold">What the dataset will contain</dt><dd className="mt-1 wrap-anywhere text-muted">{brief.dataset_contents}</dd></div>
        <div><dt className="font-semibold">Triggers</dt><dd className="mt-1 whitespace-pre-wrap wrap-anywhere text-muted">{review.input.trigger || "None; planning only"}</dd></div>
      </dl>
      {datasetUnderstandingSections(brief).map(({ label, items }) => <SummaryList key={label} label={label} items={items} />)}
      <SummaryList label="Answer before generating" items={datasetReviewQuestions(brief)} />
    </>}
    {review && <details className="dataset-details mt-5 rounded-lg border border-line p-3 text-xs">
      <summary>Original request and current rules</summary>
      <p className="mt-3 whitespace-pre-wrap wrap-anywhere text-muted">{review.input.subject}</p>
      {review.input.constraints && <p className="mt-3 whitespace-pre-wrap wrap-anywhere text-muted">{review.input.constraints}</p>}
      {review.input.source_mode === "guided" && <p className="mt-3 whitespace-pre-wrap wrap-anywhere text-muted">{review.input.inputs}</p>}
    </details>}
    <label className={`${ui.field} mt-5`}><span>Extra instructions or answers</span>
      <textarea className={ui.notesInput} aria-label="Extra instructions or answers" value={additions}
        maxLength={Math.max(0, 10000 - (review?.input.constraints?.length || 0) - 1)} disabled={working || busy}
        placeholder="Randomize the people, but at least one must have blond hair in every image."
        onChange={(event) => setAdditions(event.target.value)} />
      <small className="text-muted">Update the summary after edits, then confirm it. Cancel leaves your saved batch unchanged.</small>
    </label>
    <div className="mt-5 flex flex-wrap justify-end gap-3">
      <button className={ui.button} type="button" disabled={review?.status === "confirming"} onClick={onCancel}>Cancel</button>
      <button className={ui.button} type="button" disabled={working || busy} onClick={() => {
        onRevise(additions); setAdditions("");
      }}>{review?.status === "failed" ? "Retry analysis" : "Update summary"}</button>
      <button className={ui.primaryButton} type="button" disabled={!canConfirm} onClick={onConfirm}>{confirmLabel}</button>
    </div>
  </dialog>;
}
