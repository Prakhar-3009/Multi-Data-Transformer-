"""Data models: canonical records, fragments, provenance, and configuration."""

from src.models.enums import SourceType, ExtractionMethod
from src.models.fields import FieldValue, ProvenanceEntry
from src.models.fragments import CandidateFragment
from src.models.canonical import (
    CanonicalRecord,
    SkillEntry,
    ExperienceEntry,
    EducationEntry,
    Location,
    Links,
)
from src.models.config import OutputConfig, FieldSpec

__all__ = [
    "SourceType",
    "ExtractionMethod",
    "FieldValue",
    "ProvenanceEntry",
    "CandidateFragment",
    "CanonicalRecord",
    "SkillEntry",
    "ExperienceEntry",
    "EducationEntry",
    "Location",
    "Links",
    "OutputConfig",
    "FieldSpec",
]
