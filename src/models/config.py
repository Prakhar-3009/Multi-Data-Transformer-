"""Output configuration models — the "configurable output twist."

These models define the runtime config that reshapes the canonical record
into a consumer-specific output shape. The config is validated at LOAD TIME
(fail fast on config bugs) — data problems degrade gracefully, but a
malformed config is a developer error that should surface immediately.

The config supports:
- Field selection (subset of canonical fields)
- Renaming/remapping via "from" path
- Per-field normalization overrides
- Toggle provenance and confidence on/off
- Missing-value strategy: null / omit / error

Path mini-language (4 types):
- "full_name"         → plain field access
- "emails[0]"         → array index access
- "skills[].name"     → array projection (map sub-field over array)
- "location.city"     → nested object dot-access
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class FieldSpec(BaseModel):
    """Specification for a single output field.

    Attributes:
        path: The output key name in the final JSON.
        from_path: The canonical record path to resolve the value from.
                   Defaults to `path` if not specified.
        type: Expected output type (for documentation/validation).
        required: If True and the value is MISSING under "error" strategy,
                  a ConfigError is raised.
        normalize: Optional normalization override to apply at projection.
        on_missing: Per-field missing strategy (overrides global).
                    One of "null", "omit", "error".
    """

    path: str
    from_path: str | None = Field(default=None, alias="from")
    type: str = "string"
    required: bool = False
    normalize: str | None = None
    on_missing: str | None = None

    model_config = {"populate_by_name": True}

    @field_validator("on_missing")
    @classmethod
    def validate_on_missing(cls, v: str | None) -> str | None:
        """Ensure on_missing is one of the valid strategies."""
        if v is not None and v not in ("null", "omit", "error"):
            raise ValueError(
                f"on_missing must be 'null', 'omit', or 'error', got '{v}'"
            )
        return v

    @property
    def resolved_from(self) -> str:
        """The canonical path to resolve from (defaults to output path)."""
        return self.from_path if self.from_path is not None else self.path


class OutputConfig(BaseModel):
    """Runtime output configuration for the projection engine.

    Validated at load time — a malformed config raises immediately,
    before any candidate data is processed. This is the key distinction:
    data problems degrade gracefully; config problems fail fast.

    Attributes:
        fields: List of field specifications defining the output shape.
        include_confidence: Whether to include overall_confidence in output.
        include_provenance: Whether to include the provenance audit trail.
        on_missing: Global missing-value strategy (per-field overrides this).
    """

    fields: list[FieldSpec]
    include_confidence: bool = False
    include_provenance: bool = False
    on_missing: str = "null"

    @field_validator("on_missing")
    @classmethod
    def validate_global_on_missing(cls, v: str) -> str:
        """Ensure global on_missing is one of the valid strategies."""
        if v not in ("null", "omit", "error"):
            raise ValueError(
                f"on_missing must be 'null', 'omit', or 'error', got '{v}'"
            )
        return v

    @field_validator("fields")
    @classmethod
    def validate_non_empty_fields(cls, v: list[FieldSpec]) -> list[FieldSpec]:
        """Config must specify at least one output field."""
        if not v:
            raise ValueError("Config must specify at least one output field")
        return v
