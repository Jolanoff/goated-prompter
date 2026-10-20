"""Sequential image captioning and non-overwriting sidecar persistence."""

import base64

from ...backends.base import GoatedPrompterError
from ...backends.factory import create_backend
from ...contracts import effective_model_family
from ...director_profiles import resolve_director_config
from ...options.caption import IMAGE_TYPES
from ...uploaded_images import MAX_IMAGE_BYTES, decode_image
from .contract import caption_images, validate_caption_input
from .prompting import caption_instruction, clean_caption


def save_caption(path, caption):
    try:
        stream = path.open("x", encoding="utf-8", newline="\n")
    except FileExistsError:
        return "skipped"
    try:
        with stream as output:
            output.write(caption + "\n")
    except OSError:
        path.unlink(missing_ok=True)
        raise
    return "saved"


def run_caption(state, job, request, config, workflow):
    data = validate_caption_input(workflow["input"])
    images = caption_images(data["folder"])
    effective, profile = resolve_director_config(config, request)
    backend = create_backend(effective)
    if not backend.supports_vision:
        raise ValueError("Caption requires a vision-capable engine. Choose one in Builder or Settings.")
    family = effective_model_family(request, profile, effective)
    files = []
    with backend.generation_session() as session:
        for index, image in enumerate(images, 1):
            job.checkpoint()
            sidecar = image.with_suffix(".txt")
            row = {"image": image.name, "caption_file": sidecar.name}
            job.set_progress(f"Captioning {index}/{len(images)}: {image.name}")
            try:
                if sidecar.exists():
                    row["status"] = "skipped"
                else:
                    with image.open("rb") as stream:
                        raw = stream.read(MAX_IMAGE_BYTES + 1)
                    if len(raw) > MAX_IMAGE_BYTES:
                        raise ValueError("Image exceeds the 20 MiB limit.")
                    encoded = decode_image("data:" + IMAGE_TYPES[image.suffix.lower()] + ";base64,"
                                           + base64.b64encode(raw).decode("ascii"))
                    instruction = caption_instruction(data, encoded, family)
                    session.validate_instruction(instruction)
                    caption = clean_caption(session.generate(instruction), data["trigger"])
                    job.checkpoint()
                    row["status"] = job.commit(lambda: save_caption(sidecar, caption))
                    if row["status"] == "saved":
                        row["caption"] = caption
            except (OSError, ValueError, GoatedPrompterError) as exc:
                job.checkpoint()
                row.update(status="error", error=str(exc))
            files.append(row)
            job.record_event(f"{index}/{len(images)} {image.name}: {row['status']}")
    saved = sum(row["status"] == "saved" for row in files)
    skipped = sum(row["status"] == "skipped" for row in files)
    errors = len(files) - saved - skipped
    result = {"kind": "caption", "folder": data["folder"], "files": files,
              "saved": saved, "skipped": skipped, "errors": errors}
    job.commit(lambda: result, finish=True,
               reason=f"Captioning finished: {saved} saved, {skipped} existing, {errors} errors.")
