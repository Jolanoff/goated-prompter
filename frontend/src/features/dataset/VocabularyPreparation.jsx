import { useState } from "react";
import { api } from "../../api.js";
import { ui } from "../../ui.js";

export default function VocabularyPreparation({ busy, noEngine, onGenerate }) {
  const [review, setReview] = useState(null);
  const [selected, setSelected] = useState([]);
  const [working, setWorking] = useState(false);
  const [message, setMessage] = useState("");
  async function act(operation) {
    setWorking(true);
    setMessage("");
    try { await operation(); } catch (error) { setMessage(error.message); }
    finally { setWorking(false); }
  }
  async function load() {
    const pending = await api("/workspace/dataset/vocabulary/review");
    setReview(pending);
    setSelected([]);
  }
  async function decide(indexes) {
    const result = await api("/workspace/dataset/vocabulary/review", { token: review.token, indexes });
    setReview(null);
    setSelected([]);
    setMessage(result.approved ? `${result.approved} reviewed records saved to the structured catalog.` : "Draft rejected. The original vocabulary is unchanged.");
  }
  return <details className="dataset-details">
    <summary>Prepare private vocabulary (optional)</summary>
    <p className={ui.subtleNote}>A separate, one-time local-model conversion. Review and approve records before Dataset can use them. The original file stays unchanged; generation never runs conversion automatically.</p>
    <button className={ui.button} disabled={busy || working || noEngine} onClick={() => act(async () => {
      const job = await onGenerate("dataset/vocabulary/prepare", {});
      if (job) setMessage("Preparation started. When it finishes, open the review below.");
    })}>Prepare with saved local model</button>
    <button className={ui.button} disabled={busy || working} onClick={() => act(load)}>Open prepared records for review</button>
    {message && <p role="status">{message}</p>}
    {review && <section aria-label="Private vocabulary review">
      <p>Only explicitly selected valid records will be saved. These private drafts are not included in generation logs.</p>
      {review.rows.map((row, index) => <div key={row.line}>
        <label><input type="checkbox" disabled={busy || working || !!row.reason} checked={selected.includes(index)}
          onChange={(event) => setSelected(event.target.checked ? [...selected, index] : selected.filter((item) => item !== index))} />
          Source line {row.line} ({row.section}): {row.text}</label>
        {row.reason ? <p role="note">Rejected: {row.reason}</p> : <pre className="max-h-80 overflow-auto whitespace-pre-wrap break-words text-xs">{JSON.stringify(row.record, null, 2)}</pre>}
      </div>)}
      <button className={ui.button} disabled={busy || working || !selected.length} onClick={() => act(() => decide(selected))}>Approve selected records</button>
      <button className={ui.button} disabled={busy || working} onClick={() => act(() => decide([]))}>Reject draft</button>
    </section>}
  </details>;
}
