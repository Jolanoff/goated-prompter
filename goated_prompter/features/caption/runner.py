"""Sequential image captioning and non-overwriting sidecar persistence."""

import base64
from contextlib import ExitStack
import os

from ...backends.base import BackendConnectionError, GoatedPrompterError
from ...backends.factory import create_backend
from ...contracts import effective_model_family
from ...director_profiles import resolve_director_config
from ...options.caption import CONNECTION_ATTEMPTS_PER_IMAGE, CONNECTION_FAILURES_BEFORE_STOP, IMAGE_TYPES
from ...uploaded_images import MAX_IMAGE_BYTES, decode_image
from .contract import run_images, validate_caption_input
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


def replace_caption(path, caption):
    """Write a caption file, replacing any existing one in a single step."""
    temporary = path.with_name(f".{path.name}.saving")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as output:
            output.write(caption + "\n")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return "saved"


def write_caption(path, caption, replace):
    """Single-image runs replace the caption on purpose; folder runs never overwrite existing files."""
    return replace_caption(path, caption) if replace else save_caption(path, caption)


class _EngineSession:
    """One engine session that can be reopened after its connection drops.

    Reopening lets an owned local engine that stopped be started again; remote engines simply retry.
    """

    def __init__(self, backend):
        self.backend = backend
        self.stack = ExitStack()
        self.session = None

    def __enter__(self):
        self.session = self.stack.enter_context(self.backend.generation_session())
        return self

    def reopen(self):
        self.stack.close()
        self.stack = ExitStack()
        self.session = None
        self.session = self.stack.enter_context(self.backend.generation_session())

    def __exit__(self, *details):
        return self.stack.__exit__(*details)


def _image_payload(image):
    with image.open("rb") as stream:
        raw = stream.read(MAX_IMAGE_BYTES + 1)
    if len(raw) > MAX_IMAGE_BYTES:
        raise ValueError("Image exceeds the 20 MiB limit.")
    return decode_image("data:" + IMAGE_TYPES[image.suffix.lower()] + ";base64,"
                        + base64.b64encode(raw).decode("ascii"))


def _generate_with_reconnect(job, engine, instruction, label):
    """Generate once; after a dropped connection, reopen the engine session and retry the same image."""
    for attempt in range(1, CONNECTION_ATTEMPTS_PER_IMAGE + 1):
        try:
            engine.session.validate_instruction(instruction)
            return engine.session.generate(instruction)
        except BackendConnectionError as exc:
            job.checkpoint()
            if attempt == CONNECTION_ATTEMPTS_PER_IMAGE:
                raise
            job.record_event(f"{label}: engine connection lost ({exc}); restarting the engine session and retrying.",
                             "error")
            job.set_progress(f"{label}: engine connection lost; reconnecting "
                             f"(attempt {attempt + 1}/{CONNECTION_ATTEMPTS_PER_IMAGE})…")
            try:
                engine.reopen()
            except GoatedPrompterError as reopen_error:
                raise BackendConnectionError(f"{exc} The engine could not be restarted: {reopen_error}",
                                             completion_state=exc.completion_state) from reopen_error


def run_caption(state, job, request, config, workflow):
    data = validate_caption_input(workflow["input"])
    images = run_images(data)
    replace = bool(data["image"])
    effective, profile = resolve_director_config(config, request)
    backend = create_backend(effective)
    if not backend.supports_vision:
        raise ValueError("Caption requires a vision-capable engine. Choose one in Builder or Settings.")
    family = effective_model_family(request, profile, effective)
    files = []
    connection_failures = 0
    with _EngineSession(backend) as engine:
        for index, image in enumerate(images, 1):
            job.checkpoint()
            sidecar = image.with_suffix(".txt")
            row = {"image": image.name, "caption_file": sidecar.name}
            label = f"{index}/{len(images)} {image.name}"
            job.set_progress(f"Captioning {label}")
            try:
                if sidecar.exists() and not replace:
                    row["status"] = "skipped"
                else:
                    instruction = caption_instruction(data, _image_payload(image), family)
                    caption = clean_caption(_generate_with_reconnect(job, engine, instruction, label), data["trigger"])
                    job.checkpoint()
                    row["status"] = job.commit(lambda: write_caption(sidecar, caption, replace))
                    if row["status"] == "saved":
                        row["caption"] = caption
                connection_failures = 0
            except BackendConnectionError as exc:
                job.checkpoint()
                connection_failures += 1
                if connection_failures >= CONNECTION_FAILURES_BEFORE_STOP:
                    raise BackendConnectionError(
                        "Captioning stopped because the prompt engine connection kept failing. Check the engine "
                        "configuration and server status, then retry the remaining images. Completed caption files "
                        "have been kept. " + str(exc), completion_state=exc.completion_state,
                        partial_text=exc.partial_text, finish_reason=exc.finish_reason,
                    ) from exc
                row.update(status="error", error=f"The engine connection dropped {CONNECTION_ATTEMPTS_PER_IMAGE} times "
                                                 "on this image, so it was skipped. Run again to retry it. " + str(exc))
                try:
                    if index < len(images):
                        engine.reopen()
                except GoatedPrompterError as reopen_error:
                    raise BackendConnectionError(
                        "Captioning stopped because the prompt engine could not be restarted. Completed caption "
                        f"files have been kept. {reopen_error}", completion_state=exc.completion_state,
                    ) from reopen_error
            except (OSError, ValueError, GoatedPrompterError) as exc:
                job.checkpoint()
                row.update(status="error", error=str(exc))
            files.append(row)
            job.record_event(f"{label}: {row['status']}")
    saved = sum(row["status"] == "saved" for row in files)
    skipped = sum(row["status"] == "skipped" for row in files)
    errors = len(files) - saved - skipped
    result = {"kind": "caption", "source": "vision", "folder": data["folder"], "files": files,
              "saved": saved, "skipped": skipped, "errors": errors}
    job.commit(lambda: result, finish=True,
               reason=f"Captioning finished: {saved} saved, {skipped} existing, {errors} errors.")
