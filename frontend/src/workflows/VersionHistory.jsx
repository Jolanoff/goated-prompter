import { useMemo } from "react";
import { RotateCcw, RotateCw } from "lucide-react";
import { ui } from "../ui.js";
import { promptDiff } from "./promptDiff.js";

export function VersionDiff({ before, after }) {
  const parts = useMemo(() => promptDiff(before, after), [before, after]);
  return <details className="mt-4 rounded-lg border border-line p-3">
    <summary className="cursor-pointer text-xs font-semibold">What changed</summary>
    <p className="my-3 text-xs text-muted">Removed text is struck through; added text is highlighted.</p>
    <div className="whitespace-pre-wrap wrap-anywhere text-xs leading-[1.9]" aria-label="Prompt changes">
      {parts.map((part, index) => part.kind === "removed"
        ? <del key={index} className="bg-[#702e3740] text-[#f3b3bf]">{part.text}</del>
        : part.kind === "added" ? <ins key={index} className="bg-[#286b4640] text-[#a6eac2] no-underline">{part.text}</ins>
        : <span key={index}>{part.text}</span>)}
    </div>
  </details>;
}

export default function VersionHistory({ snapshot, current, disabled, onAction }) {
  return <section className={ui.panel} aria-label="Version history">
    <h3 className="font-display text-base font-bold">Version history</h3>
    <p className="mt-2 text-xs leading-relaxed text-muted">Every generation and refinement is saved locally. Restoring an older version keeps later versions available.</p>
    <div className={ui.inlineActions}>
      <button className={ui.button} disabled={disabled || !current?.parent_id} onClick={() => onAction({ action: "undo" })}><RotateCcw size={15} />Undo</button>
      <button className={ui.button} disabled={disabled || !snapshot.redo.length} onClick={() => onAction({ action: "redo" })}><RotateCw size={15} />Redo</button>
    </div>
    <ol className="mt-4 grid max-h-[560px] gap-2 overflow-y-auto">
      {[...snapshot.versions].reverse().map((version, index) => <li key={version.id}>
        <button className={`${ui.versionChoice} w-full`} data-active={current?.id === version.id}
          aria-current={current?.id === version.id ? "step" : undefined} disabled={disabled}
          onClick={() => onAction({ action: "restore", id: version.id })}>
          <strong className="text-xs">v{snapshot.versions.length - index} · {version.label}</strong>
          <span>{version.target} · {new Date(version.created_at).toLocaleString()}</span>
          <span className="line-clamp-2">{version.instruction || version.prompt}</span>
        </button>
      </li>)}
    </ol>
    {!!snapshot.versions.length && <button className={`${ui.textButton} mt-4`} disabled={disabled} onClick={() => {
      if (window.confirm("Clear all version history? Copy any prompts you want to keep first. Saved Prompts and comparisons are kept.")) onAction({ action: "clear_history" });
    }}>Clear version history</button>}
  </section>;
}
