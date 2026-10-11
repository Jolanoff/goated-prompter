import { Bookmark, Save, X } from "lucide-react";
import { ui } from "../../ui.js";
import { TargetSelect } from "../../shared/workflow/WorkflowControls.jsx";

export default function SavePromptDialog({ dialogRef, saveNameRef, dialogBusy, dialogError, saveName, setSaveName,
  creating, saveText, setSaveText, saveTarget, setSaveTarget, targets, onSubmit, onClose }) {
  return (
    <dialog
      className={`${ui.dialog}${creating ? " new-prompt-dialog" : ""}`}
      aria-labelledby="save-prompt-title"
      ref={dialogRef}
      onCancel={(event) => {
        if (dialogBusy) event.preventDefault();
        else onClose();
      }}
      onClose={onClose}
    >
      <form onSubmit={onSubmit}>
        <div className="mb-[18px] flex items-center justify-between">
          <div className={ui.panelIcon}>
            <Bookmark size={22} />
          </div>
          <button
            type="button"
            className={ui.iconButton}
            disabled={dialogBusy}
            onClick={onClose}
            aria-label="Close save dialog"
          >
            <X size={19} />
          </button>
        </div>
        <h2 id="save-prompt-title">{creating ? "Add a prompt" : "Save your prompt"}</h2>
        <p>
          {creating ? "Paste or write a prompt, give it a name and choose its target model."
            : "Give your prompt a name. It will be saved in a local JSON file on this server."}
        </p>
        {dialogError && (
          <div className={ui.message} role="alert">
            {dialogError}
          </div>
        )}
        <label className={ui.field}>
          <span>Prompt name</span>
          <input
            className={ui.input}
            ref={saveNameRef}
            autoFocus
            required
            maxLength={80}
            disabled={dialogBusy}
            value={saveName}
            onChange={(event) => setSaveName(event.target.value)}
          />
        </label>
        {creating && <>
          <label className={`${ui.field} mt-4`}><span>Prompt text</span>
            <textarea className={ui.outputInput} required maxLength={100000} value={saveText}
              disabled={dialogBusy} onChange={(event) => setSaveText(event.target.value)}
              placeholder="Paste a prompt here, or write your own…" />
          </label>
          <div className="mt-4"><TargetSelect label="Target model" ariaLabel="Saved prompt target"
            value={saveTarget} onChange={setSaveTarget} targets={targets} disabled={dialogBusy} /></div>
        </>}
        <button
          className={ui.primaryButton}
          disabled={dialogBusy || !saveName.trim() || (creating && !saveText.trim())}
        >
          <Save size={16} />
          {dialogBusy ? "Saving..." : "Save"}
        </button>
      </form>
    </dialog>
  );
}
