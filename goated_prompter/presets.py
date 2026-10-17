"""Protected Goated Prompter Directors plus a portable JSON user-Director library."""

from dataclasses import replace
from functools import wraps
import json
import os
from pathlib import Path
import re
import tempfile
import threading
import unicodedata

from .config import PROJECT_ROOT


USER_DIRECTOR_DIR_ENV = "GOATED_PROMPTER_USER_DIR"
_MUTATION_LOCK = threading.RLock()


def _serialized(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        with _MUTATION_LOCK:
            return function(*args, **kwargs)
    return wrapped
from .prompting.directors import (
    DEFAULT_DIRECTOR_PRESET, DIRECTOR_PRESETS, DIRECTOR_PRESET_NAMES,
    MODE_DIRECTOR_RECOMMENDATIONS, DirectorPreset, _LEGACY_DIRECTOR_ALIASES,
)
from .options.modes import MODE_NAMES

_VALID_MODES = set(MODE_NAMES)
_BUILTINS_BY_LABEL = {preset.label.casefold(): preset for preset in DIRECTOR_PRESETS}
_BUILTINS_BY_ID = {preset.id.casefold(): preset for preset in DIRECTOR_PRESETS}


class DirectorLibraryError(ValueError):
    """A user Director could not be loaded or saved safely."""


def resolve_user_director_directory():
    configured = os.environ.get(USER_DIRECTOR_DIR_ENV, "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return PROJECT_ROOT / "data" / "directors"


def recommended_director_for_mode(mode):
    return MODE_DIRECTOR_RECOMMENDATIONS.get(str(mode or "").strip(), DEFAULT_DIRECTOR_PRESET)


def _canonical_director_name(value):
    raw = str(value or "").strip()
    return _LEGACY_DIRECTOR_ALIASES.get(raw.casefold(), raw)


def _read_user_director(path):
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise DirectorLibraryError(f"Could not read user Director '{path.name}'.") from exc
    if not isinstance(payload, dict):
        raise DirectorLibraryError(f"User Director '{path.name}' must contain a JSON object.")
    if not isinstance(payload.get("name"), str) or not isinstance(payload.get("instructions"), str):
        raise DirectorLibraryError(f"User Director '{path.name}' requires string name and instructions.")
    name = payload["name"].strip()
    instructions = payload["instructions"].strip()
    recommended_mode = str(payload.get("recommended_mode") or "").strip()
    if not name or len(name) > 80:
        raise DirectorLibraryError(f"User Director '{path.name}' has an invalid name.")
    if not instructions or len(instructions) > 100000:
        raise DirectorLibraryError(f"User Director '{name}' has no instructions.")
    if recommended_mode not in _VALID_MODES:
        recommended_mode = ""
    return DirectorPreset(
        id=f"user:{path.stem}",
        label=name,
        description="User Director",
        instructions=instructions,
        recommended_mode=recommended_mode,
        source="user",
    )


def discover_user_directors(directory=None):
    library_dir = Path(directory).resolve() if directory is not None else resolve_user_director_directory()
    if not library_dir.is_dir():
        return (), ()
    directors = []
    warnings = []
    seen = set(_BUILTINS_BY_LABEL) | set(_BUILTINS_BY_ID) | set(_LEGACY_DIRECTOR_ALIASES)
    for path in sorted(library_dir.glob("*.json"), key=lambda item: item.name.casefold()):
        try:
            director = _read_user_director(path)
            key = director.label.casefold()
            if key in seen:
                raise DirectorLibraryError(f"Duplicate or protected Director name '{director.label}'.")
            seen.add(key)
            directors.append(director)
        except DirectorLibraryError as exc:
            warnings.append(str(exc))
    return tuple(directors), tuple(warnings)


def get_director_preset(value, directory=None, *, strict=False):
    """Resolve built-in, legacy, or persisted user Director by label or id."""
    name = _canonical_director_name(value)
    key = name.casefold()
    builtin = _BUILTINS_BY_LABEL.get(key) or _BUILTINS_BY_ID.get(key)
    if builtin:
        return _effective_builtin(builtin, directory)[0]
    users, _warnings = discover_user_directors(directory)
    found = next(
        (director for director in users if key in {director.label.casefold(), director.id.casefold()}),
        None,
    )
    if found:
        return found
    if strict:
        raise DirectorLibraryError("The selected Director does not exist. Select a saved Director.")
    return _effective_builtin(_BUILTINS_BY_LABEL[DEFAULT_DIRECTOR_PRESET.casefold()], directory)[0]


def list_director_presets(directory=None):
    """Return built-ins followed by automatically discovered user Directors."""
    users, warnings = discover_user_directors(directory)
    effective = [_effective_builtin(preset, directory) for preset in DIRECTOR_PRESETS]
    warnings = [*warnings, *(warning for _, warning in effective if warning)]
    directors = [*(preset for preset, _ in effective), *users]
    return [director.to_public_mapping() for director in directors], list(warnings)


def _safe_filename(name):
    normalized = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", normalized.casefold()).strip("-")
    return (slug[:64] or "user-director") + ".json"


@_serialized
def save_user_director(name, instructions, recommended_mode="", directory=None):
    """Persist a new user Director without ever overwriting a built-in or user file."""
    if not isinstance(name, str) or not isinstance(instructions, str):
        raise DirectorLibraryError("Director name and Behavior must be strings.")
    clean_name = str(name or "").strip()
    clean_instructions = str(instructions or "").strip()
    clean_mode = str(recommended_mode or "").strip()
    if not clean_name or len(clean_name) > 80:
        raise DirectorLibraryError("Director name must contain 1 to 80 characters.")
    if not clean_instructions or len(clean_instructions) > 100000:
        raise DirectorLibraryError("Director Behavior must contain 1 to 100000 characters.")
    if clean_name.casefold() in (set(_BUILTINS_BY_LABEL) | set(_BUILTINS_BY_ID) | set(_LEGACY_DIRECTOR_ALIASES)):
        raise DirectorLibraryError("Built-in Goated Prompter Directors are protected; choose a new name with Save As.")
    users, _warnings = discover_user_directors(directory)
    if any(director.label.casefold() == clean_name.casefold() for director in users):
        raise DirectorLibraryError("A user Director with that name already exists; choose a new name.")
    if clean_mode not in _VALID_MODES:
        clean_mode = ""

    library_dir = Path(directory).resolve() if directory is not None else resolve_user_director_directory()
    library_dir.mkdir(parents=True, exist_ok=True)
    destination = library_dir / _safe_filename(clean_name)
    if destination.exists():
        raise DirectorLibraryError("A Director file with that name already exists; choose a new name.")
    payload = {
        "version": 1,
        "name": clean_name,
        "instructions": clean_instructions,
        "recommended_mode": clean_mode,
    }
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", newline="\n", dir=library_dir, prefix=".goated-prompter-", suffix=".tmp", delete=False
        ) as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
            temporary = Path(handle.name)
        temporary.replace(destination)
    except OSError as exc:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
        raise DirectorLibraryError("The user Director could not be saved.") from exc
    return _read_user_director(destination), destination


@_serialized
def delete_user_director(value, directory=None):
    """Delete one persisted user Director without exposing built-ins to deletion."""
    clean_value = str(value or "").strip()
    if not clean_value:
        raise DirectorLibraryError("Select a user-created Director to delete.")
    canonical = _canonical_director_name(clean_value).casefold()
    if canonical in _BUILTINS_BY_LABEL or canonical in _BUILTINS_BY_ID:
        raise DirectorLibraryError("Built-in Goated Prompter Directors are protected and cannot be deleted.")

    library_dir = Path(directory).resolve() if directory is not None else resolve_user_director_directory()
    if not library_dir.is_dir():
        raise DirectorLibraryError("The selected user Director does not exist.")
    for path in sorted(library_dir.glob("*.json"), key=lambda item: item.name.casefold()):
        try:
            director = _read_user_director(path)
        except DirectorLibraryError:
            continue
        if canonical not in {director.label.casefold(), director.id.casefold()}:
            continue
        try:
            path.unlink()
        except OSError as exc:
            raise DirectorLibraryError("The user Director could not be deleted.") from exc
        return director, path
    raise DirectorLibraryError("The selected user Director does not exist.")


def _override_path(builtin, directory):
    root = Path(directory).resolve() if directory is not None else resolve_user_director_directory()
    return root / ".overrides" / (builtin.id + ".json")


def _effective_builtin(builtin, directory):
    path = _override_path(builtin, directory)
    if builtin.id == "minimax_director" and not path.exists():
        path = path.with_name("minimax_h3_director.json")
    if not path.exists():
        return builtin, ""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        ids, labels, modes = {builtin.id}, {builtin.label}, {builtin.recommended_mode}
        if builtin.id == "minimax_director":
            ids.add("minimax_h3_director")
            labels.add("MiniMax Director")
            modes.add("")
        if (not isinstance(payload, dict) or not isinstance(payload.get("id"), str) or payload.get("id") not in ids
                or not isinstance(payload.get("name"), str) or payload.get("name") not in labels
                or not isinstance(payload.get("instructions"), str)
                or not 1 <= len(payload["instructions"].strip()) <= 100000
                or not isinstance(payload.get("recommended_mode"), str) or payload.get("recommended_mode") not in modes):
            raise ValueError("invalid override fields")
        return replace(builtin, instructions=payload["instructions"].strip(), modified=True), ""
    except (OSError, ValueError) as exc:
        return builtin, f"Cannot read Director override '{path.name}': {exc}. Repair it or Reset explicitly."


@_serialized
def update_director(value, name, instructions, recommended_mode=None, directory=None):
    director = get_director_preset(value, directory, strict=True)
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
        raise DirectorLibraryError("Director name must contain 1 to 80 characters.")
    if not isinstance(instructions, str) or not 1 <= len(instructions.strip()) <= 100000:
        raise DirectorLibraryError("Director Behavior must contain 1 to 100000 characters.")
    name, instructions = name.strip(), instructions.strip()
    root = Path(directory).resolve() if directory is not None else resolve_user_director_directory()
    if director.source == "builtin":
        builtin = _BUILTINS_BY_ID[director.id]
        _, warning = _effective_builtin(builtin, directory)
        if warning:
            raise DirectorLibraryError(warning)
        if name != builtin.label:
            raise DirectorLibraryError("Built-in Director names cannot be changed.")
        path = _override_path(builtin, directory)
        mode = builtin.recommended_mode
    else:
        protected = set(_BUILTINS_BY_LABEL) | set(_BUILTINS_BY_ID) | set(_LEGACY_DIRECTOR_ALIASES)
        users, _ = discover_user_directors(directory)
        if name.casefold() in protected or any(p.id != director.id and p.label.casefold() == name.casefold() for p in users):
            raise DirectorLibraryError("Duplicate or protected Director name.")
        path = root / (director.id.removeprefix("user:") + ".json")
        mode = director.recommended_mode if recommended_mode is None else recommended_mode
        if mode and mode not in _VALID_MODES:
            raise DirectorLibraryError("Invalid recommended_mode.")
    payload = {"version": 1, "id": director.id, "name": name, "instructions": instructions, "recommended_mode": mode}
    temporary = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(payload, handle, ensure_ascii=True, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except OSError as exc:
        raise DirectorLibraryError("The Director could not be updated.") from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return get_director_preset(director.id, directory, strict=True), path


@_serialized
def reset_director(value, directory=None):
    key = _canonical_director_name(value).casefold()
    builtin = _BUILTINS_BY_ID.get(key) or _BUILTINS_BY_LABEL.get(key)
    if builtin is None:
        raise DirectorLibraryError("Only built-in Directors can be Reset.")
    path = _override_path(builtin, directory)
    try:
        path.unlink(missing_ok=True)
        if builtin.id == "minimax_director":
            path.with_name("minimax_h3_director.json").unlink(missing_ok=True)
    except OSError as exc:
        raise DirectorLibraryError("The Director override could not be reset.") from exc
    return builtin, path


def legacy_preset_for_mode(mode):
    """Compatibility alias retained for old payload migration."""
    return recommended_director_for_mode(mode)
