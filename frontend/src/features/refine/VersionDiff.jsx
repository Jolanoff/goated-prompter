import { useMemo } from "react";
import { promptDiff } from "./promptDiff.js";

export default function VersionDiff({ before, after }) {
  const parts = useMemo(() => promptDiff(before, after), [before, after]);
  return <details className="mt-4 rounded-lg border border-line p-3">
    <summary className="cursor-pointer text-xs font-semibold">What changed</summary>
    <p className="my-3 text-xs text-muted">Removed text is struck through; added text is highlighted.</p>
    <div className="whitespace-pre-wrap wrap-anywhere text-xs leading-[1.9]" role="region" aria-label="Prompt changes">
      {parts.map((part, index) => part.kind === "removed"
        ? <del key={index} className="diff-removed">{part.text}</del>
        : part.kind === "added" ? <ins key={index} className="diff-added">{part.text}</ins>
        : <span key={index}>{part.text}</span>)}
    </div>
  </details>;
}

