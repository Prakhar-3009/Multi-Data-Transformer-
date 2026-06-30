"""Canonical record and its sub-models — the internal source of truth.

The CanonicalRecord is the MAXIMAL superset of all candidate data. It holds
everything, including the full audit trail (provenance) and confidence scores.
The projection layer reads from this record to produce output shapes — the
record itself is never exposed directly to consumers.

Design principles:
- Arrays (emails, phones, skills) retain ALL valid values from ALL sources.
  The merge engine deduplicates and sorts them; losers are kept, not discarded.
- Scalar fields (full_name, headline) hold the survivorship winner.
- Null means "no source provided a valid value" — never invented.
- Sorted arrays ensure deterministic output (same inputs → same [0] element).
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from src.models.enums import SourceType
from src.models.fields import ProvenanceEntry


class SkillEntry(BaseModel):
    """A single canonical skill with per-skill confidence and multi-source tracking.

    A skill confirmed by two sources is at least as trustworthy as one confirmed
    by a single source. The confidence reflects the best extraction confidence
    across all sources that mentioned this skill.

    Attributes:
        name: Canonical skill name (e.g., "Machine Learning", not "ML").
        confidence: Best confidence score across all sources, ∈ [0.0, 1.0].
        sources: List of sources that mentioned this skill (for provenance).
    """

    name: str
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    sources: list[SourceType] = Field(default_factory=list)

    model_config = {"frozen": True}


class ExperienceEntry(BaseModel):
    """A single work experience entry.

    Dates are normalized to YYYY-MM format. Current positions have end=None.
    Per-field null is allowed — partial experience data is kept honestly.

    Attributes:
        company: Company name (trimmed).
        title: Job title.
        start: Start date in YYYY-MM format, or None if unknown.
        end: End date in YYYY-MM format, or None if current/unknown.
        summary: Brief description, or None.
    """

    company: str | None = None
    title: str | None = None
    start: str | None = None
    end: str | None = None
    summary: str | None = None

    model_config = {"frozen": True}


class EducationEntry(BaseModel):
    """A single education entry.

    Attributes:
        institution: School/university name.
        degree: Degree type (e.g., "B.Tech", "MS").
        field_of_study: Area of study (e.g., "Computer Science").
        end_year: Graduation year as integer, or None if unknown.
    """

    institution: str | None = None
    degree: str | None = None
    field_of_study: str | None = None
    end_year: int | None = None

    model_config = {"frozen": True}


class Location(BaseModel):
    """Structured geographic location.

    Sub-fields are independently nullable — a candidate might have a country
    but no city, or vice versa. Country is ISO-3166 alpha-2.

    Attributes:
        city: City name, or None.
        region: State/province/region, or None.
        country: ISO-3166 alpha-2 country code (e.g., "IN", "US"), or None.
    """

    city: str | None = None
    region: str | None = None
    country: str | None = None


class Links(BaseModel):
    """Profile links for the candidate.

    Each field is independently nullable. `other` is a list for any
    additional profile URLs that don't fit the named categories.

    Attributes:
        linkedin: LinkedIn profile URL, or None.
        github: GitHub profile URL, or None.
        portfolio: Personal website/portfolio URL, or None.
        other: List of additional profile URLs.
    """

    linkedin: str | None = None
    github: str | None = None
    portfolio: str | None = None
    other: list[str] = Field(default_factory=list)


class CanonicalRecord(BaseModel):
    """The internal canonical candidate record — maximal superset.

    This is the single source of truth produced by the merge engine. It is
    NEVER exposed directly to consumers; the projection layer reads from it
    to produce configurable output shapes.

    Key design decisions:
    - candidate_id is a deterministic hash of the strongest match key (email
      if available, else phone, else name). Stable across runs.
    - Arrays (emails, phones, skills) are sorted for determinism.
    - years_experience is null unless derivable deterministically from
      experience dates, tagged as method="derived" in provenance.
    - provenance contains ALL observations, not just winners.
    - overall_confidence is a weighted mean of field confidences.

    Attributes:
        candidate_id: Stable, deterministic identifier.
        full_name: Best available name, or None.
        emails: All valid, deduplicated, sorted email addresses.
        phones: All valid, deduplicated, sorted E.164 phone numbers.
        location: Structured location, or None.
        links: Profile links, or None.
        headline: Short professional descriptor, or None.
        years_experience: Total years, or None (never estimated).
        skills: Canonical skills with per-skill confidence and sources.
        experience: Work history entries.
        education: Education history entries.
        provenance: Full audit trail — all observations, winners flagged.
        overall_confidence: Aggregate trust signal, ∈ [0.0, 1.0].
    """

    candidate_id: str
    full_name: str | None = None
    emails: list[str] = Field(default_factory=list)
    phones: list[str] = Field(default_factory=list)
    current_company: str | None = None
    title: str | None = None
    location: Location | None = None
    links: Links | None = None
    headline: str | None = None
    years_experience: float | None = None
    skills: list[SkillEntry] = Field(default_factory=list)
    experience: list[ExperienceEntry] = Field(default_factory=list)
    education: list[EducationEntry] = Field(default_factory=list)
    provenance: list[ProvenanceEntry] = Field(default_factory=list)
    overall_confidence: float = Field(ge=0.0, le=1.0, default=0.0)
