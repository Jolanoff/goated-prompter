"""Dataset-type-aware staging API; independent of planning mode and quality reports."""

from .engine import GeometryValidationError, validate_geometry, geometry_issues, geometry_errors, resolve_framing_conflicts
from .migration import migrate_saved_geometry
from .prompt_schema import geometry_prompt_schema, geometry_enum_values
from .profiles import STAGING_PROFILES, StagingProfile, CHARACTER_REQUIRED_FIELDS
from .schema import GEOMETRY_FIELDS, GEOMETRY_ENUMS, FieldSpec, CUSTOM_DETAIL_FIELDS
from .rules import GeometryIssue

__all__ = ["GeometryValidationError", "validate_geometry", "geometry_issues", "geometry_errors",
           "resolve_framing_conflicts", "migrate_saved_geometry", "geometry_prompt_schema", "geometry_enum_values",
           "STAGING_PROFILES", "StagingProfile", "CHARACTER_REQUIRED_FIELDS", "GEOMETRY_FIELDS", "GEOMETRY_ENUMS",
           "FieldSpec", "CUSTOM_DETAIL_FIELDS", "GeometryIssue"]
