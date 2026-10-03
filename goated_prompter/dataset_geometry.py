"""Temporary import compatibility facade. Implementation lives in dataset_staging.

Legacy camera_view/camera_height/gaze/pose are accepted only by saved-plan
migration, not advertised as current fields. Prefer dataset_staging imports.
"""

from .dataset_staging import (
    validate_geometry, geometry_errors, geometry_issues, migrate_saved_geometry,
    resolve_framing_conflicts, geometry_prompt_schema, GeometryValidationError,
    GEOMETRY_FIELDS, GEOMETRY_ENUMS, CHARACTER_REQUIRED_FIELDS, CUSTOM_DETAIL_FIELDS,
)
from .dataset_staging.normalize import normalize_geometry_value, FRAMING_ALIASES
from .dataset_staging.schema import FREE_TEXT_FIELDS, COUNT_FIELDS
from .dataset_staging.vocabulary import *  # Historical constant imports only.
