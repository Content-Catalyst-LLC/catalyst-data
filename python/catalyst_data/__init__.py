"""Catalyst Data canonical record utilities."""

from ._version import __version__
from .engine import (
    brief_markdown,
    build_record,
    classify_record,
    classify_review,
    classify_signal,
    convert_legacy_record,
    is_canonical_record,
    percent_change,
    stable_id,
    validate_payload,
    validate_record_semantics,
)
from .validation import RecordValidationError, jsonschema_available, schema, validate_record

__all__ = [
    "__version__",
    "RecordValidationError",
    "brief_markdown",
    "build_record",
    "classify_record",
    "classify_review",
    "classify_signal",
    "convert_legacy_record",
    "is_canonical_record",
    "jsonschema_available",
    "percent_change",
    "schema",
    "stable_id",
    "validate_payload",
    "validate_record",
    "validate_record_semantics",
]
