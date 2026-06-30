"""Tagged field values and provenance entries.

FieldValue is the fundamental unit that travels through the pipeline — a raw
or normalized value annotated with its source, extraction method, and current
confidence score. It is *born* at extraction (Stage 3) and carried through
normalization and merge without losing its metadata.

ProvenanceEntry is the audit record written into the final CanonicalRecord.
It captures not just *where* a value came from, but *what* value was observed,
its confidence at merge time, and whether it won the survivorship election.
This makes merge decisions fully reconstructable — a reviewer can see every
competing value and understand why the winner was chosen.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from src.models.enums import ExtractionMethod, SourceType


class FieldValue(BaseModel):
    """A candidate field value tagged with source metadata and confidence.

    This is the unit that competes in the merge engine. The merge score is:
        field_score = source_trust × extraction_confidence × validation_score

    where `confidence` here represents extraction_confidence × validation_score
    (the two per-value factors), and source_trust is looked up from the fragment.

    Attributes:
        value: The raw or normalized field value.
        source: Which source this value originated from.
        method: How the value was extracted (direct read, regex, fuzzy, etc.).
        confidence: Current confidence in this value, ∈ [0.0, 1.0].
                    Starts as extraction_confidence, gets multiplied by
                    validation_score during normalization.
    """

    value: Any
    source: SourceType
    method: ExtractionMethod
    confidence: float = Field(ge=0.0, le=1.0)

    model_config = {"frozen": False}  # Mutable: confidence updates during pipeline


class ProvenanceEntry(BaseModel):
    """Audit record for a single field observation in the final canonical record.

    Every populated field in the CanonicalRecord has at least one ProvenanceEntry.
    When multiple sources provide the same field, ALL observations are recorded —
    the winner is flagged with is_winner=True, and losers are preserved with
    is_winner=False. This ensures nothing is silently discarded.

    Attributes:
        field: The canonical field name (e.g., "current_company", "full_name").
        source: The source that provided this observation.
        method: How the value was extracted.
        value: The actual observed value (post-normalization).
        confidence: The merge score at decision time.
        is_winner: Whether this entry won the survivorship election.
    """

    field: str
    source: SourceType
    method: ExtractionMethod
    value: Any
    confidence: float = Field(ge=0.0, le=1.0)
    is_winner: bool = False

    model_config = {"frozen": True}  # Immutable once written to the record
