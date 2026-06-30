"""End-to-end integration test — full pipeline with sample data.

This test runs the complete pipeline from files on disk through to
projected output, verifying the data flows correctly through all stages.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.core.pipeline import Pipeline
from src.models.config import OutputConfig, FieldSpec


# Paths to sample data
SAMPLE_DIR = Path("data/sample_inputs")
CSV_PATH = SAMPLE_DIR / "candidates.csv"
JSON_PATH = SAMPLE_DIR / "ats_candidates.json"
TEXT_PATH = SAMPLE_DIR / "recruiter_notes.txt"


@pytest.fixture
def pipeline() -> Pipeline:
    """Create a Pipeline instance for testing."""
    return Pipeline()


@pytest.fixture
def default_config() -> OutputConfig:
    """Load the default output config."""
    import json
    config_path = Path("data/configs/default_config.json")
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    return OutputConfig.model_validate(raw)


class TestEndToEnd:
    """Full pipeline integration tests."""

    @pytest.mark.skipif(not CSV_PATH.exists(), reason="Sample data not found")
    def test_full_pipeline_default_config(
        self, pipeline: Pipeline, default_config: OutputConfig
    ) -> None:
        """Full pipeline produces expected number of candidates."""
        results = pipeline.run(
            csv_path=CSV_PATH,
            json_path=JSON_PATH,
            text_path=TEXT_PATH,
            config=default_config,
        )

        # Should produce 14 candidates (from 27 fragments across 3 sources)
        assert len(results) == 14

        # Every result has required fields
        for r in results:
            assert "full_name" in r
            assert "primary_email" in r
            assert r["full_name"] is not None
            assert r["primary_email"] is not None

    @pytest.mark.skipif(not CSV_PATH.exists(), reason="Sample data not found")
    def test_multi_source_merge(self, pipeline: Pipeline) -> None:
        """John Smith appears in all 3 sources and merges into 1 candidate."""
        records = pipeline.run_raw(
            csv_path=CSV_PATH,
            json_path=JSON_PATH,
            text_path=TEXT_PATH,
        )

        johns = [r for r in records if r.full_name and "John" in r.full_name]
        assert len(johns) == 1, f"Expected 1 John Smith, got {len(johns)}"

        john = johns[0]
        assert john.current_company is not None
        assert len(john.emails) >= 1
        assert john.emails[0] == "john.smith@email.com"

    @pytest.mark.skipif(not CSV_PATH.exists(), reason="Sample data not found")
    def test_notes_only_candidate(self, pipeline: Pipeline) -> None:
        """Deepak Joshi only appears in notes and is still extracted."""
        records = pipeline.run_raw(
            csv_path=CSV_PATH,
            json_path=JSON_PATH,
            text_path=TEXT_PATH,
        )

        deepaks = [r for r in records if r.full_name and "Deepak" in r.full_name]
        assert len(deepaks) == 1, f"Expected 1 Deepak, got {len(deepaks)}"

    @pytest.mark.skipif(not CSV_PATH.exists(), reason="Sample data not found")
    def test_ats_only_candidate(self, pipeline: Pipeline) -> None:
        """Sneha Reddy only appears in ATS JSON and is still extracted."""
        records = pipeline.run_raw(
            csv_path=CSV_PATH,
            json_path=JSON_PATH,
            text_path=TEXT_PATH,
        )

        snehas = [r for r in records if r.full_name and "Sneha" in r.full_name]
        assert len(snehas) == 1

    @pytest.mark.skipif(not CSV_PATH.exists(), reason="Sample data not found")
    def test_custom_config_different_shape(self, pipeline: Pipeline) -> None:
        """Custom config produces different output shape from same data."""
        custom_config = OutputConfig(
            fields=[
                FieldSpec(path="candidate_name", **{"from": "full_name"}),
                FieldSpec(path="contact_email", **{"from": "emails[0]"}),
            ],
            include_confidence=False,
            include_provenance=False,
        )

        results = pipeline.run(
            csv_path=CSV_PATH,
            json_path=JSON_PATH,
            text_path=TEXT_PATH,
            config=custom_config,
        )

        assert len(results) == 14
        for r in results:
            assert "candidate_name" in r
            assert "contact_email" in r
            assert "full_name" not in r  # Renamed
            assert "overall_confidence" not in r  # Toggled off

    @pytest.mark.skipif(not CSV_PATH.exists(), reason="Sample data not found")
    def test_csv_only(self, pipeline: Pipeline, default_config: OutputConfig) -> None:
        """Pipeline works with only CSV source."""
        results = pipeline.run(csv_path=CSV_PATH, config=default_config)
        assert len(results) >= 5

    @pytest.mark.skipif(not CSV_PATH.exists(), reason="Sample data not found")
    def test_json_only(self, pipeline: Pipeline, default_config: OutputConfig) -> None:
        """Pipeline works with only JSON source."""
        results = pipeline.run(json_path=JSON_PATH, config=default_config)
        assert len(results) >= 4

    @pytest.mark.skipif(not CSV_PATH.exists(), reason="Sample data not found")
    def test_provenance_in_output(
        self, pipeline: Pipeline, default_config: OutputConfig
    ) -> None:
        """Provenance is included in default config output."""
        results = pipeline.run(
            csv_path=CSV_PATH,
            json_path=JSON_PATH,
            text_path=TEXT_PATH,
            config=default_config,
        )

        for r in results:
            assert "provenance" in r
            assert "overall_confidence" in r
            assert isinstance(r["provenance"], list)

    @pytest.mark.skipif(not CSV_PATH.exists(), reason="Sample data not found")
    def test_skills_merged_across_sources(self, pipeline: Pipeline) -> None:
        """Skills from multiple sources are unioned."""
        records = pipeline.run_raw(
            csv_path=CSV_PATH,
            json_path=JSON_PATH,
            text_path=TEXT_PATH,
        )

        # Amit Kumar has skills from CSV + ATS + Notes
        amits = [r for r in records if r.full_name and "Amit" in r.full_name]
        assert len(amits) == 1
        skill_names = [s.name for s in amits[0].skills]
        assert len(skill_names) >= 4  # At least JavaScript, React, Node.js, MongoDB
