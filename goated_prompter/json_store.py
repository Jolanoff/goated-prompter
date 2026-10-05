"""Size-bounded JSON persistence with atomic replacement and explicit corruption errors."""

import json
import os
from pathlib import Path
import tempfile

MAX_STORE_BYTES = 16 * 1024 * 1024


def atomic_json(path, payload):
    data = (json.dumps(payload, ensure_ascii=True, indent=2) + "\n").encode("utf-8")
    if len(data) > MAX_STORE_BYTES:
        raise ValueError("JSON store exceeds the 16 MiB limit. Export or remove records first.")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=path.name + ".", suffix=".tmp", delete=False) as file:
            temporary = Path(file.name)
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def read_store(path, default, validate):
    try:
        try:
            with path.open("rb") as file:
                data = file.read(MAX_STORE_BYTES + 1)
        except FileNotFoundError:
            return default
        if len(data) > MAX_STORE_BYTES:
            raise ValueError("Store exceeds the 16 MiB limit.")
        return validate(json.loads(data))
    except (OSError, ValueError, TypeError) as exc:
        raise ValueError(f"Cannot read {path}: {exc} Restore or repair this file; it has not been overwritten.") from exc
