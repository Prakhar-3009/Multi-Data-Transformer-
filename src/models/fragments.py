"""Candidate fragment — a partial record from a single source.

A CandidateFragment represents everything one source knows about one candidate.
It is the output of the extraction stage (Stage 3) and the input to entity
resolution (Stage 5). Each fragment carries:

- The source identity and trust prior
- A dictionary of field names → FieldValue (tagged values with provenance)

Fragments are designed to be incomplete — a CSV might provide name/email/phone
but not skills; a notes file might provide skills but not email. The merge
engine later combines multiple fragments into one CanonicalRecord, and the
honesty principle means missing fields stay absent (never invented).
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from src.models.enums import SourceType
from src.models.fields import FieldValue


class CandidateFragment(BaseModel):
    """A partial candidate record from a single source.

    Attributes:
        source: Which source produced this fragment.
        source_trust: The static trust prior for this source type, ∈ [0.0, 1.0].
                      Looked up from constants at extraction time.
        fields: Dictionary of canonical field names → tagged FieldValues.
                Only populated fields are present — absence means the source
                did not provide this field. This is intentional: missing ≠ null.
                A missing key means "source didn't mention this field."
                A key with FieldValue(value=None) means "source explicitly
                provided an empty/invalid value."
    """

    source: SourceType
    source_trust: float = Field(ge=0.0, le=1.0)
    fields: dict[str, FieldValue] = Field(default_factory=dict)

    def get_field_value(self, field_name: str) -> FieldValue | None:
        """Safely retrieve a field value, returning None if not present."""
        return self.fields.get(field_name)

    def has_field(self, field_name: str) -> bool:
        """Check if this fragment contains a non-None value for the field."""
        fv = self.fields.get(field_name)
        return fv is not None and fv.value is not None

    def get_value(self, field_name: str) -> object:
        """Get the raw value for a field, or None if absent/null."""
        fv = self.fields.get(field_name)
        if fv is None:
            return None
        return fv.value
