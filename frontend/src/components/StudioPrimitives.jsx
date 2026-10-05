import { ui } from "../ui.js";

export function GoatMark({ small = false }) {
  return (
    <svg className={`goat-mark ${small ? "size-10" : "size-[43px]"}`}
      viewBox="0 0 64 64" fill="none" aria-hidden="true">
      <circle cx="32" cy="32" r="31" fill="currentColor" opacity=".16" />
      <path d="M29 20C14 3 5 17 20 28M37 20C51 2 60 17 45 29"
        stroke="currentColor" strokeWidth="5" strokeLinecap="round" />
      <path d="m22 22 10-6 11 7-2 16-9 15-9-15-1-17Z" fill="currentColor" />
      <path d="m21 24-10-2 7 11 7-1m18-8 10-2-7 11-6-1" fill="currentColor" />
      <path d="m26 30 4 2m8-2-4 2m-4 8h5" stroke="#192d40"
        strokeWidth="2.5" strokeLinecap="round" />
    </svg>
  );
}

export function Panel({ icon: Icon, title, subtitle, action, children,
  className = "", collapsible = false, open = false }) {
  const Container = collapsible ? "details" : "section";
  const Header = collapsible ? "summary" : "header";
  return (
    <Container className={`${ui.panel} ${collapsible ? "collapsible-panel" : ""} ${className}`}
      {...(collapsible ? { open: open || undefined } : {})}>
      <Header className={ui.panelHeader}>
        <div className={ui.panelIcon}><Icon size={21} /></div>
        <div className={ui.panelHeading}><h2>{title}</h2><p>{subtitle}</p></div>
        {action}
      </Header>
      {children}
    </Container>
  );
}

export function Toggle({ label, description, checked, onChange, disabled }) {
  return (
    <label className={ui.toggleRow}>
      <input className={ui.toggleInput} type="checkbox" checked={!!checked}
        onChange={(event) => onChange(event.target.checked)} disabled={disabled} />
      <span className={ui.switch} aria-hidden="true" />
      <span><span className={ui.toggleLabel}>{label}</span>
        {description && <small>{description}</small>}
      </span>
    </label>
  );
}
