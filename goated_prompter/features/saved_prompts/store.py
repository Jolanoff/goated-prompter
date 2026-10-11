"""Saved prompt records stored in prompts.json."""


MAX_PROMPTS = 10000


def validate_prompts(payload):
    if not isinstance(payload, dict) or set(payload) != {"prompts"} or not isinstance(payload["prompts"], list):
        raise ValueError("Expected an object containing only a prompts array.")
    if len(payload["prompts"]) > MAX_PROMPTS:
        raise ValueError("At most 10000 saved prompts are supported.")
    records = {}
    for record in payload["prompts"]:
        required = {"id", "title", "prompt", "createdAt"}
        if not isinstance(record, dict) or not required <= record.keys() or record.keys() - required - {"target", "resolution"}:
            raise ValueError("Each prompt requires id, title, prompt, createdAt, and optionally target only.")
        record = {key: value for key, value in record.items() if key != "resolution"}
        for key, limit in (("id", 128), ("title", 80), ("prompt", 100000), ("createdAt", 64), ("target", 256)):
            if key not in record:
                continue
            value = record[key]
            if not isinstance(value, str) or len(value) > limit or (key != "target" and not value.strip()):
                raise ValueError(f"Prompt {key} must be a {'nonempty ' if key != 'target' else ''}string of at most {limit} characters.")
        if any(ord(char) < 33 or char in '/\\?#' for char in record["id"]):
            raise ValueError("Prompt id must not contain whitespace, controls, or URL path separators.")
        if record["id"] in records and records[record["id"]] != record:
            raise ValueError(f"Conflicting saved prompt id: {record['id']}")
        records[record["id"]] = dict(record)
    return {"prompts": list(records.values())}
