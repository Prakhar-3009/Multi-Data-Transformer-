"""Normalization engine — orchestrates all per-field normalizers.

This is the last per-record stage: after normalization, every fragment
speaks the same "language," so cross-record comparison (entity resolution,
merge) becomes valid. Each normalizer performs validate-then-normalize
atomically — no separate validation stage needed.

The engine takes a CandidateFragment's raw field values and returns
a new fragment with normalized values and updated confidence scores.
"""

from __future__ import annotations

import logging
from pathlib import Path

from src.models.enums import ExtractionMethod, SourceType
from src.models.fields import FieldValue
from src.models.fragments import CandidateFragment
from src.normalizers.country import normalize_country
from src.normalizers.date import normalize_date
from src.normalizers.email import normalize_email, normalize_email_list
from src.normalizers.phone import normalize_phone
from src.normalizers.skill import SkillNormalizer

logger = logging.getLogger(__name__)


class NormalizationEngine:
    """Orchestrates per-field normalization across a CandidateFragment.

    Each field type has its own normalizer. The engine dispatches by
    field name and applies the appropriate normalizer. Fields without
    a specific normalizer are passed through with light cleaning (trim).

    Attributes:
        _skill_normalizer: Cached SkillNormalizer instance.
    """

    def __init__(
        self,
        skill_dictionary_path: Path | None = None,
        default_phone_region: str = "IN",
    ) -> None:
        """Initialize the normalization engine.

        Args:
            skill_dictionary_path: Path to skill aliases JSON file.
            default_phone_region: Default region for phone parsing.
        """
        self._skill_normalizer = SkillNormalizer(
            dictionary_path=skill_dictionary_path
        )
        self._default_phone_region = default_phone_region

    def normalize_fragment(
        self, fragment: CandidateFragment
    ) -> CandidateFragment:
        """Normalize all fields in a candidate fragment.

        Returns a new fragment with normalized values and updated
        confidence scores. Fields that fail normalization are set
        to None with confidence 0.0.

        Args:
            fragment: Raw or partially processed CandidateFragment.

        Returns:
            New CandidateFragment with normalized field values.
        """
        normalized_fields: dict[str, FieldValue] = {}

        for field_name, field_value in fragment.fields.items():
            try:
                normalized = self._normalize_field(field_name, field_value)
                if normalized is not None:
                    normalized_fields[field_name] = normalized
            except Exception as e:
                # Normalization failure → field dropped (not in output)
                logger.warning(
                    "Normalization failed for field %s from %s: %s",
                    field_name, fragment.source, e,
                )

        return CandidateFragment(
            source=fragment.source,
            source_trust=fragment.source_trust,
            fields=normalized_fields,
        )

    def _normalize_field(
        self, field_name: str, field_value: FieldValue
    ) -> FieldValue | None:
        """Normalize a single field value based on its field name.

        Returns None if the value should be dropped (failed validation).
        """
        if field_value.value is None:
            return None

        raw = field_value.value

        # Dispatch by field name to the appropriate normalizer
        if field_name == "emails":
            return self._normalize_email_field(raw, field_value)
        elif field_name == "phones":
            return self._normalize_phone_field(raw, field_value)
        elif field_name == "skills":
            return self._normalize_skills_field(raw, field_value)
        elif field_name in ("location.country", "country"):
            return self._normalize_country_field(raw, field_value)
        elif field_name in (
            "experience.start", "experience.end",
            "education.end_year",
        ):
            return self._normalize_date_field(raw, field_value)
        elif field_name == "location":
            return self._normalize_location_field(raw, field_value)
        elif field_name in ("experience", "education"):
            # Structured data — pass through without text coercion
            return field_value
        elif field_name.startswith("links."):
            # URL fields — pass through without modification
            return self._normalize_text_field(raw, field_value)
        else:
            # String fields: trim whitespace
            return self._normalize_text_field(raw, field_value)

    def _normalize_email_field(
        self, raw: object, fv: FieldValue
    ) -> FieldValue | None:
        """Normalize an email value (single string or list)."""
        if isinstance(raw, list):
            normalized = normalize_email_list(raw)
            if not normalized:
                return None
            return FieldValue(
                value=normalized,
                source=fv.source,
                method=fv.method,
                confidence=fv.confidence * 1.0,  # emails validate cleanly
            )
        elif isinstance(raw, str):
            result, conf = normalize_email(raw)
            if result is None:
                return None
            return FieldValue(
                value=result,
                source=fv.source,
                method=fv.method,
                confidence=fv.confidence * conf,
            )
        return None

    def _normalize_phone_field(
        self, raw: object, fv: FieldValue
    ) -> FieldValue | None:
        """Normalize a phone value (single string or list)."""
        if isinstance(raw, list):
            normalized = []
            for phone in raw:
                result, _ = normalize_phone(str(phone), self._default_phone_region)
                if result is not None:
                    normalized.append(result)
            normalized = sorted(set(normalized))
            if not normalized:
                return None
            return FieldValue(
                value=normalized,
                source=fv.source,
                method=fv.method,
                confidence=fv.confidence * 1.0,
            )
        elif isinstance(raw, str):
            result, conf = normalize_phone(str(raw), self._default_phone_region)
            if result is None:
                return None
            return FieldValue(
                value=result,
                source=fv.source,
                method=fv.method,
                confidence=fv.confidence * conf,
            )
        return None

    def _normalize_skills_field(
        self, raw: object, fv: FieldValue
    ) -> FieldValue | None:
        """Normalize a skills value (list of skill strings)."""
        if not isinstance(raw, list):
            raw = [raw] if isinstance(raw, str) else []

        normalized_skills = []
        for skill in raw:
            if not isinstance(skill, str) or not skill.strip():
                continue
            canonical, conf = self._skill_normalizer.normalize(skill)
            if canonical is not None:
                normalized_skills.append({
                    "name": canonical,
                    "confidence": conf,
                    "raw": skill.strip(),
                })

        if not normalized_skills:
            return None

        # Deduplicate by canonical name, keeping highest confidence
        seen: dict[str, dict] = {}
        for s in normalized_skills:
            name = s["name"]
            if name not in seen or s["confidence"] > seen[name]["confidence"]:
                seen[name] = s
        deduped = sorted(seen.values(), key=lambda x: x["name"])

        return FieldValue(
            value=deduped,
            source=fv.source,
            method=fv.method,
            confidence=fv.confidence,
        )

    def _normalize_country_field(
        self, raw: object, fv: FieldValue
    ) -> FieldValue | None:
        """Normalize a country value to ISO 3166-1 alpha-2."""
        if not isinstance(raw, str):
            return None
        result, conf = normalize_country(raw)
        if result is None:
            return None
        return FieldValue(
            value=result,
            source=fv.source,
            method=fv.method,
            confidence=fv.confidence * conf,
        )

    def _normalize_date_field(
        self, raw: object, fv: FieldValue
    ) -> FieldValue | None:
        """Normalize a date value to YYYY-MM format."""
        if not isinstance(raw, str):
            return None
        result, conf = normalize_date(raw)
        if result is None:
            return None
        return FieldValue(
            value=result,
            source=fv.source,
            method=fv.method,
            confidence=fv.confidence * conf,
        )

    def _normalize_location_field(
        self, raw: object, fv: FieldValue
    ) -> FieldValue | None:
        """Normalize a location field (dict or string).

        Preserves the dict structure but normalizes the country sub-field
        to ISO-3166-α2. String locations are passed through as-is (the
        merge engine will parse them into structured Location objects).
        """
        if isinstance(raw, dict):
            # Normalize country sub-field if present
            normalized = dict(raw)
            country = normalized.get("country")
            if country and isinstance(country, str):
                norm_country, _ = normalize_country(country)
                if norm_country:
                    normalized["country"] = norm_country
            return FieldValue(
                value=normalized,
                source=fv.source,
                method=fv.method,
                confidence=fv.confidence,
            )
        elif isinstance(raw, str):
            # String location — pass through for merge engine to parse
            cleaned = raw.strip()
            if not cleaned:
                return None
            return FieldValue(
                value=cleaned,
                source=fv.source,
                method=fv.method,
                confidence=fv.confidence,
            )
        return None

    def _normalize_text_field(
        self, raw: object, fv: FieldValue
    ) -> FieldValue | None:
        """Normalize a text field: trim, validate non-empty."""
        if not isinstance(raw, str):
            # Attempt string coercion for simple types
            raw = str(raw)

        cleaned = raw.strip()
        if not cleaned:
            return None

        return FieldValue(
            value=cleaned,
            source=fv.source,
            method=fv.method,
            confidence=fv.confidence,
        )
