"""Read the generation prompt stored in image metadata and save it as the image's caption file.

Sources, in order of preference:
- a "parameters" block: written by the saver at generation time, so it holds the final prompt that was used;
- a saved node graph in API form ("prompt"): the literal text feeding the sampler's positive conditioning;
- a saved editor workflow ("workflow"): the same trace using node links and text widgets;
- a plain-text "prompt" field.

A graph only records how a prompt was produced. When the positive text passes through a node that computes it
while the workflow runs (a switch, a text generator, a join of several inputs), the final text is not stored,
so the image is reported instead of guessing.
"""

import json
import re

from PIL import Image, UnidentifiedImageError

from ...options.caption import (METADATA_CONDITIONING_WORDS, METADATA_EXCLUDED_WORD, METADATA_MODEL_INPUT,
                                METADATA_START_INPUTS, METADATA_TAG_PATTERN, METADATA_TEXT_INPUTS,
                                METADATA_TEXT_NODE_WORDS)
from .contract import run_images, validate_metadata_input
from .runner import write_caption

_FILE_NAME = re.compile(r"\.(safetensors|ckpt|pt|pth|bin|gguf|sft|onnx|png|jpe?g|webp)$", re.I)
_TAGS = re.compile(METADATA_TAG_PATTERN, re.I)
_EXIF_USER_COMMENT = 0x9286
_EXIF_IFD = 0x8769

NO_METADATA = "No generation prompt was found in this image's metadata."
COMPUTED_PROMPT = ("This image's workflow builds its prompt while it runs (for example with a switch or a text "
                   "generator), and the final text was not saved in the image, so no caption was written.")


class _Unresolved(Exception):
    """The positive text is produced at run time and is not stored in the graph."""


def _as_text(value):
    if isinstance(value, bytes):
        encoding = "utf-8"
        for prefix, prefix_encoding in ((b"UNICODE\x00", "utf-16-be"), (b"ASCII\x00\x00\x00", "utf-8")):
            if value.startswith(prefix):
                value, encoding = value[len(prefix):], prefix_encoding
                break
        value = value.decode(encoding, errors="replace")
    return value.strip("\x00").strip() if isinstance(value, str) else ""


def read_metadata(path):
    """Return the text metadata fields of an image as a lower-case keyed mapping."""
    fields = {}
    with Image.open(path) as image:
        for key, value in image.info.items():
            if isinstance(key, str) and (text := _as_text(value)):
                fields[key.casefold()] = text
        exif = image.getexif()
        values = list(exif.items()) + list(exif.get_ifd(_EXIF_IFD).items())
    for tag, value in values:
        text = _as_text(value)
        # Graph savers store "prompt:{...}" / "workflow:{...}" in EXIF text tags.
        label, separator, rest = text.partition(":")
        if separator and label.strip().casefold() in {"prompt", "workflow"} and rest.lstrip().startswith("{"):
            fields.setdefault(label.strip().casefold(), rest.strip())
        elif tag == _EXIF_USER_COMMENT and text:
            fields.setdefault("parameters", text)
    return fields


def _json_object(text):
    try:
        value = json.loads(text)
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _is_prompt_text(value):
    return isinstance(value, str) and bool(value.strip()) and not _FILE_NAME.search(value.strip())


def _conditioning_input(name):
    name = str(name).casefold()
    return METADATA_EXCLUDED_WORD not in name and any(word in name for word in METADATA_CONDITIONING_WORDS)


def _sort_key(node_id):
    return (0, int(node_id), "") if str(node_id).isdigit() else (1, 0, str(node_id))


def _trace(starts, conditioning_sources, texts_of):
    """Follow conditioning links upstream from the samplers and gather each encoder's text in order."""
    found, seen, queue = [], set(), list(starts)
    while queue:
        node_id = queue.pop(0)
        if node_id in seen:
            continue
        seen.add(node_id)
        for text in texts_of(node_id):
            if text not in found:
                found.append(text)
        queue.extend(conditioning_sources(node_id))
    return found


def prompt_from_api_graph(graph):
    """Positive prompt text from a graph saved in API form: {id: {class_type, inputs}}."""
    nodes = {str(key): node for key, node in graph.items()
             if isinstance(node, dict) and isinstance(node.get("inputs"), dict)}

    def linked(value):
        return isinstance(value, list) and len(value) == 2 and str(value[0]) in nodes

    def links(node_id):
        return [(name, str(value[0])) for name, value in nodes[node_id]["inputs"].items() if linked(value)]

    starts = []
    for node_id in sorted(nodes, key=_sort_key):
        inputs = nodes[node_id]["inputs"]
        if METADATA_MODEL_INPUT in inputs:
            starts += [str(inputs[name][0]) for name in METADATA_START_INPUTS if linked(inputs.get(name))]

    def literal_texts(node_id):
        inputs = nodes[node_id]["inputs"]
        return [inputs[name].strip() for name in METADATA_TEXT_INPUTS if _is_prompt_text(inputs.get(name))]

    def resolve(node_id, depth=0):
        """Text a linked text input receives: a constant, or a constant passed through single-input nodes."""
        texts, incoming = literal_texts(node_id), links(node_id)
        if texts and not incoming:
            return texts
        if not texts and len(incoming) == 1 and depth < 32:
            return resolve(incoming[0][1], depth + 1)
        raise _Unresolved()

    def texts_of(node_id):
        inputs, texts = nodes[node_id]["inputs"], []
        for name in METADATA_TEXT_INPUTS:
            value = inputs.get(name)
            if _is_prompt_text(value):
                texts.append(value.strip())
            elif linked(value) and not _conditioning_input(name):
                texts += resolve(str(value[0]))
        return texts

    def conditioning_sources(node_id):
        return [source for name, source in links(node_id) if _conditioning_input(name)]

    return _trace(starts, conditioning_sources, texts_of)


def prompt_from_editor_workflow(workflow):
    """Positive prompt text from an editor workflow: {nodes: [...], links: [[id, from, slot, to, slot, type]]}."""
    nodes = {str(node.get("id")): node for node in workflow.get("nodes") or [] if isinstance(node, dict)}
    sources = {}
    for link in workflow.get("links") or []:
        if isinstance(link, list) and len(link) >= 3:
            sources[link[0]] = str(link[1])
        elif isinstance(link, dict) and "id" in link:
            sources[link["id"]] = str(link.get("origin_id"))

    def links(node_id):
        return [(item.get("name"), sources[item.get("link")]) for item in nodes[node_id].get("inputs") or []
                if isinstance(item, dict) and sources.get(item.get("link")) in nodes]

    def widget_texts(node_id):
        node = nodes[node_id]
        if not any(word in str(node.get("type", "")).casefold() for word in METADATA_TEXT_NODE_WORDS):
            return []
        widgets = node.get("widgets_values")
        values = widgets.values() if isinstance(widgets, dict) else widgets if isinstance(widgets, list) else []
        return [value.strip() for value in values if _is_prompt_text(value)]

    starts = []
    for node_id in sorted(nodes, key=_sort_key):
        incoming = dict(links(node_id))
        names = {item.get("name") for item in nodes[node_id].get("inputs") or [] if isinstance(item, dict)}
        if METADATA_MODEL_INPUT in names:
            starts += [incoming[name] for name in METADATA_START_INPUTS if name in incoming]

    def resolve(node_id, depth=0):
        texts, incoming = widget_texts(node_id), links(node_id)
        if texts and not incoming:
            return texts
        if not texts and len(incoming) == 1 and depth < 32:
            return resolve(incoming[0][1], depth + 1)
        raise _Unresolved()

    def texts_of(node_id):
        text_links = [source for name, source in links(node_id) if name in METADATA_TEXT_INPUTS]
        if text_links:
            return [text for source in text_links for text in resolve(source)]
        return widget_texts(node_id)

    def conditioning_sources(node_id):
        return [source for name, source in links(node_id) if _conditioning_input(name)]

    return _trace(starts, conditioning_sources, texts_of)


def prompt_from_parameters(text):
    """Positive prompt from a parameters block: prompt, "Negative prompt: ...", then a settings line."""
    prompt = []
    for line in text.strip().splitlines():
        if line.startswith("Negative prompt:") or re.match(r"^Steps:\s*\d", line):
            break
        prompt.append(line)
    return ["\n".join(prompt).strip()] if "\n".join(prompt).strip() else []


def _clean(text):
    text = _TAGS.sub("", text)
    lines = [" ".join(line.split()) for line in text.splitlines()]
    return "\n".join(line for line in lines if line).strip()


def find_prompt(path):
    """Return (prompt, problem): the stored positive prompt, or None with a user-facing reason."""
    fields = read_metadata(path)
    computed = False
    readers = (("parameters", lambda text: text, prompt_from_parameters),
               ("prompt", _json_object, prompt_from_api_graph),
               ("workflow", _json_object, prompt_from_editor_workflow))
    for key, parse, reader in readers:
        value = parse(fields[key]) if key in fields else None
        if not value:
            continue
        try:
            texts = reader(value)
        except _Unresolved:
            computed = True
            continue
        if prompt := _clean("\n".join(texts)):
            return prompt, None
    # Some tools store the prompt itself, not a graph, under "prompt".
    plain = fields.get("prompt", "")
    if plain and _json_object(plain) is None and not plain.lstrip().startswith(("{", "[")):
        if prompt := _clean(plain):
            return prompt, None
    return None, COMPUTED_PROMPT if computed else NO_METADATA


def extract_prompt(path):
    """The stored positive prompt, or None when the image carries none that can be read."""
    return find_prompt(path)[0]


def extract_folder(value):
    """Write each image's stored prompt to a same-named text file.

    Folder runs keep existing text files; a single-image run replaces that image's file. An image without a
    readable prompt fails and its existing file, if any, is left untouched.
    """
    data = validate_metadata_input(value)
    files = []
    replace = bool(data["image"])
    for image in run_images(data):
        sidecar = image.with_suffix(".txt")
        row = {"image": image.name, "caption_file": sidecar.name}
        try:
            if sidecar.exists() and not replace:
                row["status"] = "skipped"
            else:
                prompt, problem = find_prompt(image)
                if prompt is None:
                    row.update(status="missing", error=problem)
                else:
                    caption = f"{data['trigger']}, {prompt}" if data["trigger"] else prompt
                    row["status"] = write_caption(sidecar, caption, replace)
                    if row["status"] == "saved":
                        row["caption"] = caption
        except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
            row.update(status="error", error=f"Could not read this image: {exc}")
        files.append(row)
    counts = {status: sum(row["status"] == status for row in files) for status in ("saved", "skipped", "missing", "error")}
    return {"kind": "caption", "source": "metadata", "folder": data["folder"], "files": files,
            "saved": counts["saved"], "skipped": counts["skipped"], "missing": counts["missing"],
            "errors": counts["error"]}
