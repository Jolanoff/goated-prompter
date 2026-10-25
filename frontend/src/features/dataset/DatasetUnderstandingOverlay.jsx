import { useEffect, useRef } from "react";
import { Sparkles } from "lucide-react";
import { ui } from "../../ui.js";

const statusText = {
  analyzing: "Reading your request…",
  confirming: "Request understood. Starting the scenes…",
};

// Covers the page while Understanding runs; the run then starts on its own, so nothing here needs a confirmation.
export default function DatasetUnderstandingOverlay({ understanding, onCancel }) {
  const dialog = useRef(null);
  useEffect(() => {
    if (understanding && !dialog.current?.open) dialog.current?.showModal();
    else if (!understanding && dialog.current?.open) dialog.current.close();
  }, [understanding]);
  const failed = understanding?.status === "failed";
  return <dialog ref={dialog} className="dataset-understanding" aria-labelledby="dataset-understanding-status"
    onCancel={(event) => { event.preventDefault(); onCancel(); }}>
    {!failed && <div className="dataset-pulse" aria-hidden="true"><span /><span /><span /><Sparkles size={30} /></div>}
    <p id="dataset-understanding-status" role="status">{failed ? "Stopped before the scenes started." : statusText[understanding?.status]}</p>
    {failed && <p className={ui.warningNote} role="alert">{understanding.error}</p>}
    <button className={ui.button} type="button" onClick={onCancel} autoFocus>{failed ? "Close" : "Cancel"}</button>
  </dialog>;
}
