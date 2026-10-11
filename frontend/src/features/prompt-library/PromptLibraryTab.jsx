import { Pencil, Plus, RotateCw, Save, Trash2 } from "lucide-react";
import { ui } from "../../ui.js";
import { usePromptLibrary } from "./usePromptLibrary.js";

export default function PromptLibraryTab({ visible, targets, initialTarget, onNotice }) {
  const { target, library, loading, saving, error, editor, draft, dirty, deleting,
    setDraft, selectTarget, edit, cancel, reload, requestDelete, cancelDelete, save, remove,
  } = usePromptLibrary({ visible, initialTarget, onNotice });
  const ready = library?.target === target && !loading;
  const editorForm = (adding) => (
    <form className="library-editor" onSubmit={(event) => { event.preventDefault(); save(); }}>
      <label className={ui.field}>
        <span>{adding ? "New prompt" : "Edit prompt"}</span>
        <textarea className="control textarea library-prompt-input" aria-label="Library prompt"
          autoFocus required value={draft} disabled={saving}
          onChange={(event) => setDraft(event.target.value)}
          placeholder="Paste a finished prompt that captures how you like to write." />
      </label>
      <div className="library-editor-footer">
        <p>Keep paragraphs and tags. Save one prompt at a time.</p>
        <div className={ui.inlineActions}>
          <button type="button" className={ui.button} disabled={saving} onClick={cancel}>Cancel</button>
          <button className={ui.primaryButton} disabled={saving || !dirty || !draft.trim()}>
            <Save size={14} />{saving ? "Saving…" : adding ? "Add prompt" : "Save changes"}
          </button>
        </div>
      </div>
    </form>
  );

  return (
    <section className="prompt-library-view" hidden={!visible} aria-label="Prompt library editor">
      <div className={ui.pageHeading}>
        <div><h2>Prompt Library</h2>
          <p>Good examples for the final writer. Add prompts that sound like you.</p>
        </div>
      </div>
      <div className="library-toolbar">
        <label className={ui.field}>
          <span>Target model</span>
          <select className={ui.select} aria-label="Library target model" value={target}
            disabled={saving} onChange={(event) => selectTarget(event.target.value)}>
            {targets.map((name) => <option key={name}>{name}</option>)}
          </select>
        </label>
        <div className={ui.inlineActions}>
          <button className={ui.iconButton} onClick={reload} disabled={saving || loading}
            aria-label="Reload library" title="Reload library"><RotateCw size={16} /></button>
          <button className={ui.primaryButton} onClick={() => edit()} disabled={!ready || saving}>
            <Plus size={16} />New prompt
          </button>
        </div>
      </div>
      {error && <div className={ui.message} role="alert"><span>{error}</span>
        <button className={ui.button} onClick={reload} disabled={saving || loading}>Reload library</button>
      </div>}
      {loading && <p className="library-feedback" role="status">Loading prompts…</p>}
      {ready && <div className="library-list">
        <header className="library-list-header">
          <h3>{target} prompts</h3>
          <span>{library.prompts.length} prompt{library.prompts.length === 1 ? "" : "s"}</span>
        </header>
        {editor?.index === null && editorForm(true)}
        {library.prompts.length ? <ul aria-label={`${target} library prompts`}>
          {library.prompts.map((prompt, index) => (
            <li className="library-row" key={`${library.revision}-${index}`}>
              {editor?.index === index ? editorForm(false) : <>
                <button className="library-preview" onClick={() => edit(index)} disabled={saving}
                  aria-label={`Open prompt ${index + 1}`} title="View and edit prompt">
                  <span>{prompt}</span>
                </button>
                <div className="library-row-actions">
                  <button className={ui.iconButton} onClick={() => edit(index)} disabled={saving}
                    aria-label={`Edit prompt ${index + 1}`} title="Edit prompt"><Pencil size={15} /></button>
                  <button className={ui.deleteButton} onClick={() => requestDelete(index)} disabled={saving}
                    aria-label={`Delete prompt ${index + 1}`} title="Delete prompt"><Trash2 size={15} /></button>
                </div>
              </>}
              {deleting === index && <div className="library-delete-confirm" role="alert">
                <span>Delete this prompt from {target}?</span>
                <div className={ui.inlineActions}>
                  <button className={ui.button} disabled={saving} onClick={cancelDelete}>Cancel</button>
                  <button className={`${ui.button} text-danger`} disabled={saving} onClick={remove}>
                    {saving ? "Deleting…" : "Delete prompt"}
                  </button>
                </div>
              </div>}
            </li>
          ))}
        </ul> : editor === null && <div className="library-empty">
          <h3>No prompts for {target} yet</h3>
          <p>Add a finished prompt to give the final writer an example of your writing style.</p>
          <button className={ui.button} onClick={() => edit()}><Plus size={15} />Add your first prompt</button>
        </div>}
        <footer className="library-file-note" title={library.path}>
          Saved to <span>{library.file}</span>. You can still edit the text file directly.
        </footer>
      </div>}
    </section>
  );
}
