import { Bookmark, Save, X } from "lucide-react";
import { ui } from "../../ui.js";

export default function SavePromptDialog({ dialogRef, saveNameRef, dialogBusy, dialogError, saveName, setSaveName,
  onSubmit, onClose }) {
  return (
    <dialog
      className={ui.dialog}
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
        <h2 id="save-prompt-title">Save your prompt</h2>
        <p>
          Give your prompt a name. It will be saved in a local JSON file on
          this server.
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
        <button
          className={ui.primaryButton}
          disabled={dialogBusy || !saveName.trim()}
        >
          <Save size={16} />
          {dialogBusy ? "Saving..." : "Save"}
        </button>
      </form>
    </dialog>
  );
}
