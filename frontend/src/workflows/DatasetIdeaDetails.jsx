import { datasetIdeaDetails } from "./datasetState.js";

export default function DatasetIdeaDetails({ item }) {
  const details = datasetIdeaDetails(item);
  if (!details.length) return null;
  return <dl className="grid gap-3 text-xs leading-relaxed" aria-label={`Idea ${item.index} planning details`}>
    {details.map(({ field, label, text }) => <div key={field}>
      <dt className="font-semibold">{label}</dt>
      <dd className="mt-1 wrap-anywhere text-muted">{text}</dd>
    </div>)}
  </dl>;
}

export function DatasetSceneCheck({ item }) {
  if (!("self_check" in item)) return null;
  return <div className="mt-3 text-xs leading-relaxed" aria-label={`Scene ${item.index} self-check`}>
    <h3 className="font-semibold">Scene self-check</h3>
    <p className="mt-1 whitespace-pre-wrap wrap-anywhere text-muted">{item.self_check || "Self-check pending"}</p>
  </div>;
}
