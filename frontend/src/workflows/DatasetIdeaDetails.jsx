import { useId, useState } from "react";
import { Camera, CircleAlert, Eye, MapPin, Scan, Trees } from "lucide-react";
import { datasetIdeaDetails } from "./datasetState.js";

const planningHints = {
  placement: { icon: MapPin, description: "Where subjects sit in the image and how they relate." },
  visibility: { icon: Eye, description: "Which subject features should stay visible." },
  camera: { icon: Camera, description: "Camera angle, distance, and viewpoint." },
  framing: { icon: Scan, description: "How the subjects fit within the image." },
  context: { icon: Trees, description: "The setting, surroundings, and background." },
};

export default function DatasetIdeaDetails({ item }) {
  const tooltipId = useId();
  const [activeField, setActiveField] = useState(null);
  const details = datasetIdeaDetails(item);
  const active = details.find(({ field }) => field === activeField);
  if (!details.length) return null;
  return <div className="dataset-direction-tools" role="group" aria-label={`Idea ${item.index} planning details`}
    aria-description="Idea suggestions, not requirements. The checked scene may adjust these details to satisfy required rules."
    onMouseLeave={(event) => {
      if (!event.currentTarget.contains(document.activeElement)) setActiveField(null);
    }}
    onBlur={(event) => {
      if (!event.currentTarget.contains(event.relatedTarget)) setActiveField(null);
    }}
    onKeyDown={(event) => {
      if (event.key === "Escape" && active) { event.preventDefault(); setActiveField(null); }
    }}>
    {details.map(({ field, label, text }) => {
      const { icon: Icon, description } = planningHints[field];
      return <button key={field} type="button" className="dataset-direction-button" aria-label={label}
        aria-description={`${description} ${text}`} aria-describedby={active?.field === field ? tooltipId : undefined}
        onMouseEnter={() => setActiveField(field)} onFocus={() => setActiveField(field)} onClick={() => setActiveField(field)}>
        <Icon size={17} aria-hidden="true" />
      </button>;
    })}
    {active && <div className="dataset-direction-popover" id={tooltipId} role="tooltip">
      <div className="dataset-direction-tooltip">
        <strong>{active.label}</strong>
        <p className="dataset-direction-description">{planningHints[active.field].description}</p>
        <p className="dataset-direction-value">{active.text}</p>
        <small>Planning suggestion; required rules take priority.</small>
      </div>
    </div>}
  </div>;
}

export function DatasetSceneCheck({ item }) {
  const check = typeof item.self_check === "string" ? item.self_check.trim() : "";
  if (!check || /^PASS$/i.test(check)) return null;
  return <div className="dataset-scene-warning" role="note" aria-label={`Scene ${item.index} self-check`}>
    <CircleAlert size={17} aria-hidden="true" />
    <div><h3>Scene needs attention</h3>
      <p className="whitespace-pre-wrap wrap-anywhere">{check}</p></div>
  </div>;
}
