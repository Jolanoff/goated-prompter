import { ChevronDown, ImagePlus, Settings2, X } from "lucide-react";
import { Panel } from "../components/StudioPrimitives.jsx";
import { ui } from "../ui.js";

export default function ReferenceImages({ images, settings, attributes, sources,
  missingReferences, sourceAvailable, onChange, onUpload, onRemove, onError }) {
  const hasImages = images.some(Boolean);
  return (
    <>
      <Panel icon={ImagePlus} title="Reference images" subtitle="Add up to four images to guide your prompt."
        action={<span className={ui.countChip}>{images.filter(Boolean).length} / 4</span>}>
        <div className="grid grid-cols-2 gap-[11px]">
          {images.map((image, index) => (
            <div className={ui.imageSlot} data-image={!!image} key={index}
              onDragOver={(event) => event.preventDefault()}
              onDrop={(event) => {
                event.preventDefault();
                if (event.dataTransfer.files.length !== 1)
                  onError("Drop one image into each slot. The limit is four references.");
                else onUpload(event.dataTransfer.files[0], index);
              }}>
              {image ? (
                <>
                  <img src={image.data} alt={`Reference ${index + 1}: ${image.name}`} />
                  <button className={ui.imageRemove} aria-label={`Remove image ${index + 1}`}
                    onClick={() => onRemove(index)}><X size={15} /></button>
                  <div className={ui.imageCaption}>
                    <span>IMAGE {index + 1}</span><span title={image.name}>{image.name}</span>
                  </div>
                </>
              ) : (
                <label className={ui.uploadLabel}>
                  <input type="file" aria-label={`Upload image ${index + 1}`}
                    accept="image/png,image/jpeg,image/webp"
                    onChange={(event) => {
                      onUpload(event.target.files[0], index);
                      event.target.value = "";
                    }} />
                  <span className="mb-[3px] text-accent [&>svg]:inline [&>svg]:align-baseline">
                    <ImagePlus size={24} />
                  </span>
                  <strong>Add image {index + 1}</strong>
                  <span>Drop here or click to browse</span><small>PNG, JPG, WEBP</small>
                </label>
              )}
            </div>
          ))}
        </div>
        <p className={ui.subtleNote}>
          Images are not saved. References need reuploading after
          reload; unavailable preserve mappings reset to Off.
        </p>
      </Panel>
      <Panel icon={Settings2} title="Keep from reference images"
        subtitle="Choose which image supplies each attribute to keep." collapsible open={hasImages}>
        <div className={ui.referenceMap}>
          {attributes.map(({ key: attribute, label }) => (
            <label className={ui.referenceRow} key={attribute}>
              <span>{label}</span><span className={ui.selectWrap}>
                <select className={ui.select}
                  aria-label={`${attribute.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase())} source`}
                  value={hasImages ? settings[`reference_${attribute}_source`] : "Off"}
                  disabled={!hasImages}
                  onChange={(event) => onChange(`reference_${attribute}_source`, event.target.value)}>
                  {sources.map((source) => (
                    <option key={source} disabled={!sourceAvailable(source)}>{source}</option>
                  ))}
                </select><ChevronDown size={13} />
              </span>
            </label>
          ))}
        </div>
        <p className={ui.subtleNote}>
          Off adds no explicit preserve constraint. Blend
          uses all uploaded images and requires at least two.
        </p>
        {!!missingReferences.length && <p className={ui.warningNote} role="alert">
          Missing references for {missingReferences.map(({ label }) => label).join(", ")}
          . Reupload the mapped images or select Off. Blend
          needs at least two images. Text-only preview ignores these mappings.
        </p>}
      </Panel>
    </>
  );
}
