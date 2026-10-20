"""Size-bounded JSON persistence with atomic replacement and explicit corruption errors."""

import json
import os
from pathlib import Path
import tempfile
import time

MAX_STORE_BYTES = 16 * 1024 * 1024


def _replace(source, destination, attempts=5, delay=0.05):
    """os.replace, retrying briefly on Windows where antivirus, indexers or sync clients may hold the target open."""
    for attempt in range(attempts):
        try:
            os.replace(source, destination)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(delay * (attempt + 1))


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
        _replace(temporary, path)
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
