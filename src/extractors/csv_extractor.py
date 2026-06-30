"""CSV extractor — converts parsed CSV rows into CandidateFragments.

The CSV source is the highest-reliability structured source. Fields map
almost directly to canonical names (e.g., "name" → "full_name",
"email" → "emails"). Extraction is straightforward with high confidence.

Every field extracted here is tagged with:
- source: SourceType.CSV
- method: ExtractionMethod.DIRECT_FIELD_READ
- confidence: EXTRACTION_CONFIDENCE[DIRECT_FIELD_READ] = 0.95
"""

from __future__ import annotations

import logging

from src.core.constants import EXTRACTION_CONFIDENCE, SOURCE_TRUST
from src.extractors.base import BaseExtractor
from src.models.enums import ExtractionMethod, SourceType
from src.models.fields import FieldValue
from src.models.fragments import CandidateFragment

logger = logging.getLogger(__name__)

# CSV column name → canonical field name mapping
# Handles common variations in recruiter CSV exports
_CSV_FIELD_MAP: dict[str, str] = {
    # Name variants
    "name": "full_name",
    "full_name": "full_name",
    "full name": "full_name",
    "candidate_name": "full_name",
    "candidate name": "full_name",
    # Email variants
    "email": "emails",
    "emails": "emails",
    "email_address": "emails",
    "email address": "emails",
    "contact_email": "emails",
    # Phone variants
    "phone": "phones",
    "phones": "phones",
    "phone_number": "phones",
    "phone number": "phones",
    "contact_phone": "phones",
    "mobile": "phones",
    # Company variants
    "company": "current_company",
    "current_company": "current_company",
    "current company": "current_company",
    "employer": "current_company",
    "organization": "current_company",
    # Title variants
    "title": "title",
    "job_title": "title",
    "job title": "title",
    "position": "title",
    "role": "title",
    # Location
    "location": "location",
    "city": "location.city",
    "state": "location.region",
    "region": "location.region",
    "country": "location.country",
    # Skills
    "skills": "skills",
    "skill": "skills",
    "technical_skills": "skills",
    "technical skills": "skills",
    # Other
    "headline": "headline",
    "summary": "headline",
    "linkedin": "links.linkedin",
    "linkedin_url": "links.linkedin",
    "github": "links.github",
    "github_url": "links.github",
    "years_experience": "years_experience",
    "years of experience": "years_experience",
    "experience_years": "years_experience",
}


class CSVExtractor(BaseExtractor):
    """Extracts CandidateFragments from parsed CSV rows.

    Each row becomes one CandidateFragment. Fields are mapped from
    CSV column names to canonical names, and tagged with DIRECT_FIELD_READ
    extraction method and high confidence.
    """

    def extract(self, raw_records: list[dict]) -> list[CandidateFragment]:
        """Convert CSV rows into CandidateFragments.

        Args:
            raw_records: List of row dicts from RecruiterCSVParser.

        Returns:
            List of CandidateFragments, one per valid row.
        """
        fragments: list[CandidateFragment] = []
        base_confidence = EXTRACTION_CONFIDENCE[ExtractionMethod.DIRECT_FIELD_READ]
        trust = SOURCE_TRUST[SourceType.CSV]

        for i, row in enumerate(raw_records):
            try:
                fragment = self._extract_row(row, base_confidence, trust)
                if fragment.fields:  # Only keep fragments with at least one field
                    fragments.append(fragment)
            except Exception as e:
                logger.warning("CSV extraction failed for row %d: %s", i, e)
                continue

        logger.info("Extracted %d fragments from %d CSV rows", len(fragments), len(raw_records))
        return fragments

    def _extract_row(
        self, row: dict, confidence: float, trust: float
    ) -> CandidateFragment:
        """Extract a single CSV row into a CandidateFragment."""
        fields: dict[str, FieldValue] = {}

        for csv_key, value in row.items():
            if value is None:
                continue

            # Map CSV column name to canonical field name
            canonical = _CSV_FIELD_MAP.get(csv_key)
            if canonical is None:
                # Unknown column — skip (don't invent mappings)
                continue

            # Handle special field types
            if canonical == "skills":
                # Skills may be comma-separated in CSV
                value = self._parse_skills_string(value)
            elif canonical in ("emails", "phones"):
                # Wrap scalar as list for consistency
                if isinstance(value, str):
                    value = [v.strip() for v in value.split(",") if v.strip()]
            elif canonical == "years_experience":
                value = self._parse_years_experience(value)
                if value is None:
                    continue

            fields[canonical] = FieldValue(
                value=value,
                source=SourceType.CSV,
                method=ExtractionMethod.DIRECT_FIELD_READ,
                confidence=confidence,
            )

        return CandidateFragment(
            source=SourceType.CSV,
            source_trust=trust,
            fields=fields,
        )

    @staticmethod
    def _parse_skills_string(value: object) -> list[str]:
        """Parse a comma/semicolon separated skills string into a list."""
        if isinstance(value, list):
            return value
        if not isinstance(value, str):
            return []
        # Split on comma, semicolon, or pipe
        skills = []
        for s in value.replace(";", ",").replace("|", ",").split(","):
            cleaned = s.strip()
            if cleaned:
                skills.append(cleaned)
        return skills

    @staticmethod
    def _parse_years_experience(value: object) -> float | None:
        """Parse years of experience, returning None if not a valid number."""
        if isinstance(value, (int, float)):
            return float(value) if value >= 0 else None
        if isinstance(value, str):
            try:
                parsed = float(value.strip())
                return parsed if parsed >= 0 else None
            except ValueError:
                return None
        return None
