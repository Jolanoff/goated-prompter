import { useEffect, useRef } from "react";
import { Download, LoaderCircle, X } from "lucide-react";
import { ui } from "../../ui.js";
import { canConfirmDatasetReview } from "./datasetState.js";
import { visualDirectionSummary } from "./visualDirection.js";
import { canRemovePart, dismissNote, groupedParts, intentKinds, intentStatus, linkChoices, memberChoices, partName, partSentence,
  removePart, setLinks, setMember, setRelationEnd, setTerms } from "./datasetIntent.js";

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

function LinkEditor({ intent, item, field, onChange }) {
  const choices = linkChoices(intent, item, field);
  if (!choices.length) return null;
  return <fieldset className="dataset-intent-links"><legend>{field === "by" ? "Done by" : "Done to"}</legend>
    {choices.map((other) => <label key={other.id}><input type="checkbox" checked={item[field].includes(other.id)}
      onChange={(event) => onChange(setLinks(intent, item.id, field, event.target.checked
        ? [...item[field], other.id] : item[field].filter((id) => id !== other.id)))} />{partName(intent, other.id)}</label>)}
  </fieldset>;
}

function MemberEditor({ intent, item, characters, onChange }) {
  const choices = memberChoices(item, characters);
  if (choices.length < 2 || !Object.hasOwn(item, "member")) return null;
  const name = partName(intent, item.id);
  return <label className="dataset-intent-terms"><span>Person represented by {name}</span>
    <select className={ui.select} aria-label={`Person represented by ${name}`} value={item.member || 0}
      onChange={(event) => onChange(setMember(intent, item.id, Number(event.target.value), characters))}>
      <option value={0}>Whole group</option>
      {choices.map(({ label, member }) => <option key={member} value={member}>{label}</option>)}
    </select></label>;
}

const scoped = (text, item) => item.input > 0 ? `Guided input ${item.input}: ${text}` : text;
const relationSentence = (intent, relation) => `${partName(intent, relation.a)} ${relation.rel} ${partName(intent, relation.b)}`;

function ReviewList({ title, items }) {
  return <section className="dataset-review-list" aria-label={title}><h3>{title}</h3>
    {items.length ? <ul>{[...new Set(items)].map((text) => <li className="whitespace-pre-wrap wrap-anywhere" key={text}>{text}</li>)}</ul>
      : <p>None specified</p>}
  </section>;
}

function IntentNotes({ intent }) {
  if (!intent) return null;
  return <>
    {!!intent.warnings.length && <ul className="dataset-intent-warnings" aria-label="Details to check">
      {intent.warnings.map((warning, index) => <li className="wrap-anywhere" key={index}>{warning}</li>)}</ul>}
    {!!intent.unresolved.length && <section className="dataset-review-questions" aria-label="Left unclear (not guessed)">
      <h3>Left unclear (not guessed)</h3><ul>{intent.unresolved.map((note, index) => <li className="wrap-anywhere" key={index}>{note}</li>)}</ul>
    </section>}
  </>;
}

function SceneReview({ brief }) {
  const intent = brief.intent?.available ? brief.intent : null;
  const parts = intent?.elements || [];
  const actions = parts.filter((item) => ["action", "pose"].includes(item.kind) && item.status === "fixed");
  const partsFor = (status) => parts.filter((item) => item.status === status && (item.kind !== "subject" || status !== "fixed"))
    .filter((item) => status !== "fixed" || !actions.includes(item)).map((item) => scoped(partSentence(intent, item), item));
  const relationsFor = (status) => (intent?.relations || []).filter((relation) => relation.status === status)
    .map((relation) => scoped(relationSentence(intent, relation), intent.elements.find((item) => item.id === relation.a && item.input > 0)
      || intent.elements.find((item) => item.id === relation.b) || {}));
  return <>
    {brief.path !== "non_character" && <PeopleBar characters={brief.characters} />}
    {intent && <><p className="dataset-review-note">Interpreted actions and links—not additional requirements.</p>
      <ReviewList title="What happens" items={[...actions.map((item) => scoped(partSentence(intent, item), item)), ...relationsFor("fixed")]} /></>}
    <div className="dataset-review-requirements">
      <ReviewList title="Stays the same" items={[brief.fixed, ...brief.must].filter(Boolean)} />
      <ReviewList title="Changes per image" items={[brief.randomized].filter(Boolean)} />
      {intent && <ReviewList title="Allowed" items={[...partsFor("optional"), ...relationsFor("optional")]} />}
      <ReviewList title="Ruled out" items={brief.avoid} />
    </div>
    <IntentNotes intent={brief.intent} />
  </>;
}

/** Understanding v10: the request part by part. Read-only unless the review is ready and edits are wired. */
function IntentDetails({ intent, characters, onChange }) {
  if (!intent) return null;
  const editable = !!onChange && intent.available;
  return <section className="dataset-review-intent" aria-label="Structured details">
    <h3>Details</h3>
    <p className="dataset-review-note">How the request was read, part by part, for vocabulary matching. The summary and constraints
      above stay what the scenes follow. Corrections here are checked again on Confirm; to change what the request says, use Revise.
      These annotations are not additional requirements. Related ideas are inferred search hints. Separate them with commas.</p>
    {intent.available && <>
      {groupedParts(intent).map(([kind, items]) => <div className="dataset-intent-group" key={kind}><h4>{intentKinds[kind]}</h4>
        <ul>{items.map((item) => <li key={item.id}>
          <div className="dataset-intent-part">
            <span className="wrap-anywhere">{partSentence(intent, item)}</span>
            <span className="dataset-intent-status" data-status={item.status}>Interpreted: {intentStatus[item.status]}</span>
            {item.source === "suggested" && <span className="dataset-intent-suggested">Suggested</span>}
            {!!item.cast.length && <small>{item.cast.join(", ")}</small>}
            {item.input > 0 && <small>Guided input {item.input} only</small>}
            {editable && canRemovePart(intent, item) && <button type="button" className={ui.textButton}
              aria-label={`Remove ${item.text}`} onClick={() => onChange(removePart(intent, item.id))}>Remove</button>}
          </div>
          {editable && item.kind === "subject" && <MemberEditor intent={intent} item={item} characters={characters} onChange={onChange} />}
          {editable ? <label className="dataset-intent-terms"><span>Related ideas (inferred)</span>
            <input key={item.terms.join(",")} className={ui.input} aria-label={`Related ideas (inferred) for ${partName(intent, item.id)}`} defaultValue={item.terms.join(", ")}
              maxLength={300} onBlur={(event) => onChange(setTerms(intent, item.id, event.target.value))} /></label>
            : !!item.terms.length && <p className="dataset-intent-hint">Related ideas (inferred): {item.terms.join(", ")}</p>}
          {editable && ["action", "pose"].includes(item.kind) && <details className="dataset-intent-correct"><summary>Correct who does what</summary>
            <LinkEditor intent={intent} item={item} field="by" onChange={onChange} />
            {item.kind === "action" && <LinkEditor intent={intent} item={item} field="to" onChange={onChange} />}</details>}
        </li>)}</ul></div>)}
      {!!intent.relations.length && <div className="dataset-intent-group"><h4>How parts relate</h4><ul>
        {intent.relations.map((relation) => <li key={relation.id}><div className="dataset-intent-part">
          {editable ? <>{["a", "b"].map((end, position) => <span key={end} className="contents">
            {position === 1 && <span>{relation.rel}</span>}
            <select className={ui.select} aria-label={`${end === "a" ? "First" : "Second"} part of “${relation.rel}”`} value={relation[end]}
              onChange={(event) => onChange(setRelationEnd(intent, relation.id, end, event.target.value))}>
              {intent.elements.map((item) => <option key={item.id} value={item.id}>{partName(intent, item.id)}</option>)}</select></span>)}</>
            : <span className="wrap-anywhere">{partName(intent, relation.a)} {relation.rel} {partName(intent, relation.b)}</span>}
          <span className="dataset-intent-status" data-status={relation.status}>Interpreted: {intentStatus[relation.status]}</span></div></li>)}
      </ul></div>}
      {!!intent.unresolved.length && <div className="dataset-intent-group"><h4>Left unclear (not guessed)</h4><ul>
        {intent.unresolved.map((note, index) => <li key={index}><div className="dataset-intent-part"><span className="wrap-anywhere">{note}</span>
          {editable && <button type="button" className={ui.textButton} aria-label={`Dismiss: ${note}`}
            onClick={() => onChange(dismissNote(intent, index))}>Dismiss</button>}</div></li>)}</ul></div>}
    </>}
  </section>;
}

export default function DatasetConfirmationModal({ review, busy, directorLabel, onConfirm, onCancel, onExport, onEditIntent }) {
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
      <details className="dataset-review-details">
      <summary>Details and corrections</summary>
      <IntentDetails intent={brief.intent} characters={brief.characters} onChange={review.status === "ready" ? onEditIntent : undefined} />
      <section className="dataset-review-output" aria-label="Output settings">
        <h3>Output settings</h3>
        <dl>
          <div><dt>Style</dt><dd>{brief.settings.style || "Not specified"}</dd></div>
          <div><dt>Target model</dt><dd>{brief.settings.target || "Not specified"}</dd></div>
          <div><dt>Director</dt><dd>{directorLabel || brief.settings.director || "Not specified"}</dd></div>
          {review.vocabulary_packs && <div><dt>Vocabulary packs</dt><dd className="wrap-anywhere">{["Core", ...review.vocabulary_packs].join(", ")}
            <small className="block text-muted">Recorded with this run on Confirm, with any packs they require.</small></dd></div>}
          {review.visual_direction && <div><dt>Visual direction</dt><dd className="wrap-anywhere">{visualDirectionSummary(review.visual_direction)}
            <small className="block text-muted">Only for what the request leaves open; your own camera and light wording is kept.</small></dd></div>}
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
