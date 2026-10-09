import { ArrowLeft, ArrowUpRight, Bookmark, Copy, Plus, Trash2 } from "lucide-react";
import { ui } from "../../ui.js";

export default function SavedPromptsTab({ records, ready, busy, deletingDisabled,
  onBack, onCopy, onOpen, onDelete }) {
  return (
    <>
      <div className={ui.pageHeading}>
        <div><h2>Saved prompts</h2>
          <p>Your prompt library, saved on this server and ready to use again.</p>
        </div>
        <button className={ui.button} onClick={onBack}>
          <ArrowLeft size={16} />Back to builder
        </button>
      </div>
      {!ready ? (
        <div className={ui.emptyState}>
          <Bookmark size={34} /><h3>Saved prompts are not ready yet</h3>
          <p>Loading from the local server. If the connection fails, retry above.</p>
        </div>
      ) : records.length === 0 ? (
        <div className={ui.emptyState}>
          <div className={ui.emptyIcon}><Bookmark size={30} /></div>
          <h3>Keep your best prompts here</h3>
          <p>Create a prompt in Builder, then choose Save Prompt to add it to your library.</p>
          <button className={ui.primaryButton} onClick={onBack}>
            <Plus size={16} />Create a prompt
          </button>
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-[18px] mobile:grid-cols-1">
          {records.map((record) => (
            <article className={ui.savedCard} key={record.id}>
              <div className={ui.savedMeta}>
                <span>{record.target || "Prompt"}</span>
                <time dateTime={record.createdAt}>
                  {new Date(record.createdAt).toLocaleDateString(undefined,
                    { month: "short", day: "numeric", year: "numeric" })}
                </time>
              </div>
              <h3>{record.title}</h3><pre tabIndex={0}>{record.prompt}</pre>
              <div className="flex gap-2 border-t border-line pt-[15px]">
                <button className={ui.button} onClick={() => onCopy(record.prompt)}>
                  <Copy size={15} />Copy
                </button>
                <button className={ui.button} disabled={busy} onClick={() => onOpen(record)}>
                  <ArrowUpRight size={15} />Open
                </button>
                <button className={ui.deleteButton} aria-label={`Delete ${record.title}`}
                  disabled={deletingDisabled} onClick={() => onDelete(record)}>
                  <Trash2 size={17} />
                </button>
              </div>
            </article>
          ))}
        </div>
      )}
    </>
  );
}
