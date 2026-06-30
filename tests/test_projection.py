"""Tests for projection engine — path resolver and output shaping.

Tests the config-driven projection layer ("the twist"): verifying
that different configs produce different output shapes from the
same canonical records.
"""

from __future__ import annotations

import pytest

from src.models.canonical import CanonicalRecord, Location, Links, SkillEntry
from src.models.config import OutputConfig, FieldSpec
from src.models.enums import SourceType
from src.models.fields import ProvenanceEntry
from src.projection.path_resolver import MISSING, resolve_path
from src.projection.projector import project


def _make_record(**overrides) -> CanonicalRecord:
    """Helper to build a CanonicalRecord for testing."""
    defaults = {
        "candidate_id": "test123",
        "full_name": "John Smith",
        "emails": ["john@test.com", "john.smith@work.com"],
        "phones": ["+919876543210"],
        "current_company": "Google",
        "title": "Senior SWE",
        "location": Location(city="Bangalore", region="Karnataka", country="IN"),
        "links": Links(linkedin="https://linkedin.com/in/jsmith", github="https://github.com/jsmith"),
        "headline": "Senior Software Engineer",
        "years_experience": 8.0,
        "skills": [
            SkillEntry(name="Python", confidence=0.95, sources=[SourceType.CSV, SourceType.ATS_JSON]),
            SkillEntry(name="ML", confidence=0.90, sources=[SourceType.ATS_JSON]),
        ],
        "provenance": [
            ProvenanceEntry(field="full_name", source=SourceType.CSV, method="direct_field_read", value="John Smith", confidence=0.95, is_winner=True),
        ],
        "overall_confidence": 0.92,
    }
    defaults.update(overrides)
    return CanonicalRecord(**defaults)


class TestPathResolver:
    """Tests for the path resolver."""

    def test_plain_field(self) -> None:
        """Resolves plain field access."""
        record = {"full_name": "John"}
        assert resolve_path(record, "full_name") == "John"

    def test_array_index(self) -> None:
        """Resolves array index access."""
        record = {"emails": ["a@b.com", "c@d.com"]}
        assert resolve_path(record, "emails[0]") == "a@b.com"
        assert resolve_path(record, "emails[1]") == "c@d.com"

    def test_array_index_out_of_bounds(self) -> None:
        """Out-of-bounds array index returns MISSING."""
        record = {"emails": ["a@b.com"]}
        assert resolve_path(record, "emails[5]") is MISSING

    def test_array_projection(self) -> None:
        """Resolves array projection: skills[].name."""
        record = {"skills": [{"name": "Python"}, {"name": "Java"}]}
        result = resolve_path(record, "skills[].name")
        assert result == ["Python", "Java"]

    def test_dot_access(self) -> None:
        """Resolves dot access: location.city."""
        record = {"location": {"city": "NYC", "country": "US"}}
        assert resolve_path(record, "location.city") == "NYC"

    def test_missing_field_returns_missing(self) -> None:
        """Nonexistent field returns MISSING, not None."""
        assert resolve_path({}, "nonexistent") is MISSING

    def test_null_field_returns_none(self) -> None:
        """Existing field with None value returns None (not MISSING)."""
        record = {"full_name": None}
        result = resolve_path(record, "full_name")
        assert result is None
        assert result is not MISSING

    def test_missing_is_falsy(self) -> None:
        """MISSING sentinel is falsy."""
        assert not MISSING

    def test_missing_vs_none(self) -> None:
        """MISSING and None are distinct."""
        assert MISSING is not None
        assert MISSING != None  # noqa: E711


class TestProjector:
    """Tests for the projection engine."""

    def test_basic_projection(self) -> None:
        """Projects with plain field paths."""
        record = _make_record()
        config = OutputConfig(fields=[
            FieldSpec(path="name", **{"from": "full_name"}),
            FieldSpec(path="email", **{"from": "emails[0]"}),
        ])
        result = project(record, config)
        assert result["name"] == "John Smith"
        assert result["email"] == "john@test.com"

    def test_different_config_different_shape(self) -> None:
        """Same record, different config → different output keys."""
        record = _make_record()

        config1 = OutputConfig(fields=[
            FieldSpec(path="full_name"),
            FieldSpec(path="current_company"),
        ])
        config2 = OutputConfig(fields=[
            FieldSpec(path="candidate_name", **{"from": "full_name"}),
            FieldSpec(path="employer", **{"from": "current_company"}),
        ])

        result1 = project(record, config1)
        result2 = project(record, config2)

        assert "full_name" in result1
        assert "candidate_name" in result2
        assert result1["full_name"] == result2["candidate_name"]

    def test_missing_field_null_strategy(self) -> None:
        """Missing field with 'null' strategy → None in output."""
        record = _make_record(headline=None)
        config = OutputConfig(
            fields=[FieldSpec(path="headline")],
            on_missing="null",
        )
        result = project(record, config)
        assert result["headline"] is None

    def test_missing_field_omit_strategy(self) -> None:
        """Missing field with 'omit' strategy → key absent from output."""
        record = _make_record()
        config = OutputConfig(fields=[
            FieldSpec(path="nonexistent_field", on_missing="omit"),
        ])
        result = project(record, config)
        assert "nonexistent_field" not in result

    def test_confidence_toggle(self) -> None:
        """include_confidence flag controls confidence in output."""
        record = _make_record()
        config_with = OutputConfig(
            fields=[FieldSpec(path="full_name")],
            include_confidence=True,
        )
        config_without = OutputConfig(
            fields=[FieldSpec(path="full_name")],
            include_confidence=False,
        )
        assert "overall_confidence" in project(record, config_with)
        assert "overall_confidence" not in project(record, config_without)

    def test_provenance_toggle(self) -> None:
        """include_provenance flag controls provenance in output."""
        record = _make_record()
        config_with = OutputConfig(
            fields=[FieldSpec(path="full_name")],
            include_provenance=True,
        )
        config_without = OutputConfig(
            fields=[FieldSpec(path="full_name")],
            include_provenance=False,
        )
        assert "provenance" in project(record, config_with)
        assert "provenance" not in project(record, config_without)

    def test_skills_projection(self) -> None:
        """Projects skills with array projection path."""
        record = _make_record()
        config = OutputConfig(fields=[
            FieldSpec(path="skill_names", **{"from": "skills[].name"}),
        ])
        result = project(record, config)
        assert result["skill_names"] == ["Python", "ML"]

    def test_location_dot_access(self) -> None:
        """Projects nested location fields."""
        record = _make_record()
        config = OutputConfig(fields=[
            FieldSpec(path="city", **{"from": "location.city"}),
            FieldSpec(path="country", **{"from": "location.country"}),
        ])
        result = project(record, config)
        assert result["city"] == "Bangalore"
        assert result["country"] == "IN"
