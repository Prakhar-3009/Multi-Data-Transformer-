"""Enumeration types for source identification and extraction method tracking.

These enums enforce a closed vocabulary for provenance metadata, ensuring
that every field value's origin is described using a known, deterministic
set of labels — never free-form strings.
"""

from enum import Enum


class SourceType(str, Enum):
    """Identifies the origin source of a candidate data fragment.

    Each value corresponds to one of the supported ingestion sources.
    Inherits from str so Pydantic serializes to the string value directly,
    making JSON output human-readable.
    """

    CSV = "csv"
    ATS_JSON = "ats_json"
    RECRUITER_NOTES = "recruiter_notes"


class ExtractionMethod(str, Enum):
    """Describes how a field value was extracted from its source.

    The method directly impacts extraction_confidence scoring:
    - DIRECT_FIELD_READ: highest confidence (structured, labeled column)
    - ATS_MAPPED: slightly lower (schema mapping introduces risk)
    - REGEX_EXTRACTED: moderate (pattern match in free text)
    - FUZZY_MATCHED: score-dependent (similarity threshold governs confidence)
    - DERIVED: computed from other fields (e.g., years_experience from dates)
    """

    DIRECT_FIELD_READ = "direct_field_read"
    ATS_MAPPED = "ats_mapped"
    REGEX_EXTRACTED = "regex_extracted"
    FUZZY_MATCHED = "fuzzy_matched"
    DERIVED = "derived"
