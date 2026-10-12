import { useEffect, useState } from "react";
import { api } from "../../api.js";
import { ui } from "../../ui.js";

export default function VocabularyPreparation({ busy, noEngine, onGenerate, job }) {
  const [review, setReview] = useState(null);
  const [selected, setSelected] = useState([]);
  const [working, setWorking] = useState(false);
  const [message, setMessage] = useState("");
  const [status, setStatus] = useState(null);
  const preparation = job?.kind === "dataset_vocabulary" ? job : null;
  useEffect(() => {
    if (job?.kind !== "dataset_vocabulary" || job.status !== "succeeded") return;
    let current = true;
    api("/workspace/dataset/vocabulary/status").then((value) => {
      if (current) setStatus(value);
    }).catch((error) => { if (current) setMessage(error.message); });
    return () => { current = false; };
  }, [job?.id, job?.kind, job?.status]);
  async function refreshStatus() {
    setStatus(await api("/workspace/dataset/vocabulary/status"));
  }
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
    await refreshStatus();
  }
  async function decide(indexes) {
    const result = await api("/workspace/dataset/vocabulary/review", { token: review.token, indexes });
    setReview(null);
    setSelected([]);
    setMessage(result.approved ? `${result.approved} reviewed records saved to the structured catalog.` : "Draft rejected. The original vocabulary is unchanged.");
    await refreshStatus();
  }
  const pending = preparation && ["queued", "running", "cancelling"].includes(preparation.status);
  const awaiting = status?.state === "awaiting_review" ? status
    : !status && preparation?.status === "succeeded" ? preparation.result : null;
  return <details className="dataset-details" onToggle={(event) => {
    if (event.currentTarget.open) void act(refreshStatus);
  }}>
    <summary>Prepare private vocabulary (optional)</summary>
    <p className={ui.subtleNote}>A separate, one-time local-model conversion. Review and approve records before Dataset can use them. The original file stays unchanged; generation never runs conversion automatically.</p>
    <p className={ui.subtleNote}>Default catalog: <code>data/vocabulary/sexual.txt.catalog.json</code>. Preparation creates a review draft, not an approved catalog.</p>
    {status?.catalog_path && <p className={ui.subtleNote}>Catalog output: <code>{status.catalog_path}</code></p>}
    {pending ? <p role="status">Preparation pending. {preparation.progress || "The local model is preparing records for review."}</p>
      : awaiting ? <p role="status">{awaiting.validated} valid records awaiting approval · {awaiting.rejected} rejected. No catalog is saved until you approve selected records.</p>
        : status?.state === "saved" ? <p role="status">Catalog saved: {status.approved} approved records. Dataset loads compatible records for the next batch.</p>
          : status?.state === "stale_catalog" ? <p role="status">The saved catalog is stale or invalid. Prepare and review again; general planning remains available.</p>
            : status?.state === "stale_review" ? <p role="status">The review draft is stale or invalid. Prepare again before approving records.</p>
              : status?.state === "not_prepared" ? <p role="status">No approved catalog or pending review. Start preparation, then review and approve valid records.</p> : null}
    {preparation && ["failed", "cancelled", "interrupted"].includes(preparation.status) && <p role="status">Preparation {preparation.status}. No new records were approved. Check status before preparing again.</p>}
    <button className={ui.button} disabled={busy || working || noEngine} onClick={() => act(async () => {
      const job = await onGenerate("dataset/vocabulary/prepare", {});
      if (job) setMessage("Preparation started. When it finishes, open the review below.");
    })}>Prepare with saved local model</button>
    <button className={ui.button} disabled={busy || working} onClick={() => act(load)}>Open prepared records for review</button>
    <button className={ui.button} disabled={working} onClick={() => act(refreshStatus)}>Check catalog status</button>
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
