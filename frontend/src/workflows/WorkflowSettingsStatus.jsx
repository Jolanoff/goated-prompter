import { ui } from "../ui.js";

export default function WorkflowSettingsStatus({ settings, label }) {
  return <div className="mb-4 text-xs text-muted" aria-label={`${label} settings save status`}>
    <span aria-live="polite">{label} settings: {settings.status}</span>
    {settings.error && <div className={`${ui.message} mt-3`} role="alert">
      <span>{settings.error} Your local draft is kept.</span>
      {!settings.conflict && settings.record && <button className={ui.retryButton} disabled={settings.working} onClick={() => settings.flush().catch(() => {})}>Retry {label} save</button>}
      <button className={ui.retryButton} disabled={settings.working} onClick={() => {
        if (!settings.record || window.confirm(`Reload saved ${label} settings and discard local edits?`)) settings.reload();
      }}>Reload {label} settings</button>
    </div>}
  </div>;
}
