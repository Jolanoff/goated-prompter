import { LockKeyhole } from "lucide-react";
import { packChoices, recordedPackSummary, roleLabels, selectionProblem, shortFingerprint, statusLabels, togglePack } from "./packSelection.js";

/** Choose the packs one Dataset run (or one inspection) uses. Never changes the global Pack Manager settings. */
export function PackSelector({ packs, selected, onChange, disabled, label = "Vocabulary packs", error }) {
  const rows = packChoices(packs, selected);
  const problem = selectionProblem(rows);
  return <fieldset className="pack-selector" aria-label={label} disabled={disabled}>
    <legend>{label}</legend>
    <p className="pack-selector-help">Choose content packs for this run. Core interfaces load internally; packs a selected pack needs are added automatically. Your global Pack Manager settings are not changed.</p>
    {error && <p className="pack-selector-problem" role="alert">{error}</p>}
    <ul>
      {rows.map((row) => {
        const optional = !row.mandatory && row.role !== "dependency";
        return <li key={`${row.origin}:${row.id}`} data-role={row.role} data-status={row.status}>
          <label>
            <input type="checkbox" aria-label={`Use ${row.name}`} checked={row.role !== "off"}
              disabled={disabled || !optional || (row.role === "off" && row.status !== "ok")}
              onChange={() => optional && onChange(togglePack(selected, row.id))} />
            {row.mandatory && <LockKeyhole size={13} aria-hidden="true" />}
            <span className="pack-selector-name">{row.name}</span>
            <span className="pack-selector-version">{row.version ? `v${row.version}` : "version unavailable"}</span>
            <span className="pack-selector-role">{roleLabels[row.role]}</span>
            {row.status !== "ok" && <span className="pack-selector-status">{statusLabels[row.status]}{row.missing.length ? `: ${row.missing.join(", ")}` : ""}</span>}
            {row.role !== "off" && row.status === "ok" && !row.mandatory && !row.enabledGlobally && <span className="pack-selector-note">Off in Pack Manager; used for this run only</span>}
          </label>
        </li>;
      })}
    </ul>
    {problem && <p className="pack-selector-problem" role="alert">{problem}</p>}
  </fieldset>;
}

/** A stored run's recorded pack configuration, read-only. */
export function RecordedPacks({ recorded, status, names = {}, title = "Vocabulary packs for this run" }) {
  const summary = recordedPackSummary(recorded, status);
  return <section className="pack-selector" data-state={summary.state} aria-label={title}>
    <h3>{title}: {summary.label}</h3>
    {summary.note && <p className="pack-selector-help">{summary.note}</p>}
    {!!summary.rows.length && <ul>
      {summary.rows.map((row) => <li key={row.id} data-role={row.role}>
        <span className="pack-selector-name">{names[row.id] || row.id}</span>
        <span className="pack-selector-version">v{row.version}</span>
        <span className="pack-selector-role">{roleLabels[row.role]}</span>
        <code title={row.fingerprint}>{shortFingerprint(row.fingerprint)}</code>
        {row.disabledGlobally && <span className="pack-selector-note">Off in Pack Manager now; this run keeps it</span>}
        {row.drift.map((item, index) => <span className="pack-selector-status" key={index}>{item.problem}: {item.detail}</span>)}
      </li>)}
    </ul>}
  </section>;
}
