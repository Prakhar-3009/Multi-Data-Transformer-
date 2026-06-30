"""Tests for extractors — CSV, JSON, and text extraction.

Tests the structure → domain object layer, verifying that extractors
correctly convert parsed dicts into CandidateFragments with tagged fields.
"""

from __future__ import annotations

import pytest

from src.extractors.csv_extractor import CSVExtractor
from src.extractors.json_extractor import ATSJSONExtractor
from src.extractors.text_extractor import TextExtractor
from src.models.enums import ExtractionMethod, SourceType


class TestCSVExtractor:
    """Tests for CSVExtractor."""

    def test_basic_extraction(self) -> None:
        """Extracts core fields from a CSV row."""
        rows = [{"name": "John Smith", "email": "john@test.com", "company": "Google"}]
        fragments = CSVExtractor().extract(rows)

        assert len(fragments) == 1
        f = fragments[0]
        assert f.source == SourceType.CSV
        assert f.get_field_value("full_name").value == "John Smith"
        assert f.get_field_value("emails").value == ["john@test.com"]
        assert f.get_field_value("current_company").value == "Google"

    def test_skills_parsed(self) -> None:
        """Skills string is split into a list."""
        rows = [{"name": "Test", "skills": "Python, Java, SQL"}]
        fragments = CSVExtractor().extract(rows)

        skills = fragments[0].get_field_value("skills").value
        assert isinstance(skills, list)
        assert "Python" in skills
        assert "SQL" in skills

    def test_unknown_columns_skipped(self) -> None:
        """Unknown column names are ignored, not mapped."""
        rows = [{"name": "Test", "favorite_color": "blue"}]
        fragments = CSVExtractor().extract(rows)

        assert fragments[0].get_field_value("full_name").value == "Test"
        assert fragments[0].get_field_value("favorite_color") is None

    def test_empty_row_produces_no_fragment(self) -> None:
        """Row with all None values produces no fragment."""
        rows = [{"name": None, "email": None}]
        fragments = CSVExtractor().extract(rows)
        assert len(fragments) == 0

    def test_extraction_confidence(self) -> None:
        """CSV extraction uses DIRECT_FIELD_READ method."""
        rows = [{"name": "Test"}]
        fragments = CSVExtractor().extract(rows)
        fv = fragments[0].get_field_value("full_name")
        assert fv.method == ExtractionMethod.DIRECT_FIELD_READ


class TestATSJSONExtractor:
    """Tests for ATSJSONExtractor."""

    def test_basic_extraction(self) -> None:
        """Extracts core fields using ATS field mapping."""
        records = [{"candidate_name": "John Smith", "contact_email": "john@t.com"}]
        fragments = ATSJSONExtractor().extract(records)

        assert len(fragments) == 1
        f = fragments[0]
        assert f.source == SourceType.ATS_JSON
        assert f.get_field_value("full_name").value == "John Smith"

    def test_nested_employer_extraction(self) -> None:
        """Extracts company from nested employer block."""
        records = [{"candidate_name": "Test", "employer": {"name": "Google", "title": "SWE"}}]
        fragments = ATSJSONExtractor().extract(records)

        assert fragments[0].get_field_value("current_company").value == "Google"
        assert fragments[0].get_field_value("title").value == "SWE"

    def test_technical_skills_array(self) -> None:
        """Extracts skills from technical_skills array."""
        records = [{"candidate_name": "Test", "technical_skills": ["Python", "Java"]}]
        fragments = ATSJSONExtractor().extract(records)

        skills = fragments[0].get_field_value("skills").value
        assert "Python" in skills

    def test_extraction_method(self) -> None:
        """ATS extraction uses ATS_MAPPED method."""
        records = [{"candidate_name": "Test"}]
        fragments = ATSJSONExtractor().extract(records)
        fv = fragments[0].get_field_value("full_name")
        assert fv.method == ExtractionMethod.ATS_MAPPED

    def test_empty_record_skipped(self) -> None:
        """Empty record produces no fragment."""
        fragments = ATSJSONExtractor().extract([{}])
        assert len(fragments) == 0


class TestTextExtractor:
    """Tests for TextExtractor."""

    def test_email_extraction(self) -> None:
        """Extracts email from free text."""
        records = [{"raw_text": "Contact john@test.com for details."}]
        fragments = TextExtractor().extract(records)

        emails = fragments[0].get_field_value("emails").value
        assert "john@test.com" in emails

    def test_phone_extraction(self) -> None:
        """Extracts phone from free text."""
        records = [{"raw_text": "Phone: +919876543210\nEmail: a@b.com"}]
        fragments = TextExtractor().extract(records)

        phones = fragments[0].get_field_value("phones")
        assert phones is not None

    def test_name_extraction_labeled(self) -> None:
        """Extracts name from labeled pattern."""
        records = [{"raw_text": "Candidate: John Smith\nEmail: john@test.com"}]
        fragments = TextExtractor().extract(records)

        name = fragments[0].get_field_value("full_name")
        assert name is not None
        assert name.value == "John Smith"

    def test_skills_extraction(self) -> None:
        """Extracts skills from labeled pattern."""
        records = [{"raw_text": "Email: a@b.com\nSkills: Python, Java, SQL"}]
        fragments = TextExtractor().extract(records)

        skills = fragments[0].get_field_value("skills")
        assert skills is not None
        assert len(skills.value) >= 2

    def test_empty_text_skipped(self) -> None:
        """Empty text produces no fragment."""
        records = [{"raw_text": ""}]
        fragments = TextExtractor().extract(records)
        assert len(fragments) == 0

    def test_extraction_method(self) -> None:
        """Text extraction uses REGEX_EXTRACTED method."""
        records = [{"raw_text": "Email: test@test.com"}]
        fragments = TextExtractor().extract(records)
        fv = fragments[0].get_field_value("emails")
        assert fv.method == ExtractionMethod.REGEX_EXTRACTED

    def test_conservative_name_extraction(self) -> None:
        """Name extraction rejects ambiguous patterns (not 2-4 alpha words)."""
        records = [{"raw_text": "Email: a@b.com\nThe candidate mentioned working on Project Alpha."}]
        fragments = TextExtractor().extract(records)

        name = fragments[0].get_field_value("full_name") if fragments else None
        # Should NOT extract "Project Alpha" as a name
        if name:
            assert "Project" not in name.value
