"""Tests for parsers — CSV, JSON, and text parsing.

Tests the bytes → structure layer, verifying that each parser
correctly converts raw files into lists of dictionaries.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from src.core.exceptions import ParseError
from src.parsers.csv_parser import RecruiterCSVParser
from src.parsers.json_parser import ATSJSONParser
from src.parsers.text_parser import RecruiterNotesParser


class TestRecruiterCSVParser:
    """Tests for RecruiterCSVParser."""

    def test_basic_csv(self, tmp_path: Path) -> None:
        """Parses a well-formed CSV correctly."""
        csv = tmp_path / "test.csv"
        csv.write_text("name,email,phone\nJohn Smith,john@test.com,123456\n", encoding="utf-8")

        parser = RecruiterCSVParser()
        records = parser.parse(csv)

        assert len(records) == 1
        assert records[0]["name"] == "John Smith"
        assert records[0]["email"] == "john@test.com"

    def test_keys_lowercased(self, tmp_path: Path) -> None:
        """Column headers are lowercased."""
        csv = tmp_path / "test.csv"
        csv.write_text("Name,EMAIL,Phone Number\nJohn,j@t.com,123\n", encoding="utf-8")

        records = RecruiterCSVParser().parse(csv)
        assert "name" in records[0]
        assert "email" in records[0]
        assert "phone number" in records[0]

    def test_empty_values_become_none(self, tmp_path: Path) -> None:
        """Empty/whitespace-only values are converted to None."""
        csv = tmp_path / "test.csv"
        csv.write_text("name,email\nJohn,\nJane,  \n", encoding="utf-8")

        records = RecruiterCSVParser().parse(csv)
        assert len(records) == 2
        assert records[0]["email"] is None
        assert records[1]["email"] is None

    def test_empty_rows_skipped(self, tmp_path: Path) -> None:
        """Rows with all-None values are skipped."""
        csv = tmp_path / "test.csv"
        csv.write_text("name,email\n,\nJane,jane@t.com\n", encoding="utf-8")

        records = RecruiterCSVParser().parse(csv)
        assert len(records) == 1
        assert records[0]["name"] == "Jane"

    def test_duplicate_rows_deduplicated(self, tmp_path: Path) -> None:
        """Exact duplicate rows are skipped."""
        csv = tmp_path / "test.csv"
        csv.write_text("name,email\nJohn,j@t.com\nJohn,j@t.com\n", encoding="utf-8")

        records = RecruiterCSVParser().parse(csv)
        assert len(records) == 1

    def test_semicolon_delimiter(self, tmp_path: Path) -> None:
        """Handles semicolon-delimited CSV."""
        csv = tmp_path / "test.csv"
        csv.write_text("name;email;phone\nJohn;j@t.com;123\n", encoding="utf-8")

        records = RecruiterCSVParser().parse(csv)
        assert len(records) == 1
        assert records[0]["name"] == "John"

    def test_nonexistent_file_raises_parse_error(self) -> None:
        """Missing file raises ParseError."""
        with pytest.raises(ParseError):
            RecruiterCSVParser().parse(Path("/nonexistent.csv"))

    def test_empty_file_returns_empty(self, tmp_path: Path) -> None:
        """Empty file returns empty list, no error."""
        csv = tmp_path / "empty.csv"
        csv.write_text("", encoding="utf-8")

        records = RecruiterCSVParser().parse(csv)
        assert records == []

    def test_encoding_fallback(self, tmp_path: Path) -> None:
        """Handles non-UTF-8 encoded files via fallback."""
        csv = tmp_path / "test.csv"
        csv.write_bytes(b"name,email\nJos\xe9,jose@t.com\n")  # Latin-1

        records = RecruiterCSVParser().parse(csv)
        assert len(records) == 1
        assert "jos" in records[0]["name"].lower()


class TestATSJSONParser:
    """Tests for ATSJSONParser."""

    def test_basic_json_array(self, tmp_path: Path) -> None:
        """Parses a JSON array of candidates."""
        f = tmp_path / "test.json"
        data = [{"name": "John"}, {"name": "Jane"}]
        f.write_text(json.dumps(data), encoding="utf-8")

        records = ATSJSONParser().parse(f)
        assert len(records) == 2

    def test_nested_candidates_key(self, tmp_path: Path) -> None:
        """Extracts candidates from nested key."""
        f = tmp_path / "test.json"
        data = {"candidates": [{"name": "John"}, {"name": "Jane"}]}
        f.write_text(json.dumps(data), encoding="utf-8")

        records = ATSJSONParser().parse(f)
        assert len(records) == 2

    def test_single_candidate_dict(self, tmp_path: Path) -> None:
        """Wraps a single candidate dict in a list."""
        f = tmp_path / "test.json"
        data = {"name": "John", "email": "john@t.com"}
        f.write_text(json.dumps(data), encoding="utf-8")

        records = ATSJSONParser().parse(f)
        assert len(records) == 1
        assert records[0]["name"] == "John"

    def test_invalid_json_raises_parse_error(self, tmp_path: Path) -> None:
        """Invalid JSON raises ParseError."""
        f = tmp_path / "bad.json"
        f.write_text("{not valid json", encoding="utf-8")

        with pytest.raises(ParseError):
            ATSJSONParser().parse(f)

    def test_empty_file_returns_empty(self, tmp_path: Path) -> None:
        """Empty JSON file returns empty list."""
        f = tmp_path / "empty.json"
        f.write_text("", encoding="utf-8")

        records = ATSJSONParser().parse(f)
        assert records == []

    def test_nonexistent_file_raises_parse_error(self) -> None:
        """Missing file raises ParseError."""
        with pytest.raises(ParseError):
            ATSJSONParser().parse(Path("/nonexistent.json"))


class TestRecruiterNotesParser:
    """Tests for RecruiterNotesParser."""

    def test_single_block(self, tmp_path: Path) -> None:
        """Single candidate text block."""
        f = tmp_path / "notes.txt"
        f.write_text("Met John Smith today. Great candidate.", encoding="utf-8")

        records = RecruiterNotesParser().parse(f)
        assert len(records) == 1
        assert "John Smith" in records[0]["raw_text"]

    def test_multiple_blocks_separator(self, tmp_path: Path) -> None:
        """Multiple candidates separated by ---."""
        f = tmp_path / "notes.txt"
        f.write_text("John Smith is great.\n\n---\n\nJane Doe is solid.", encoding="utf-8")

        records = RecruiterNotesParser().parse(f)
        assert len(records) == 2

    def test_empty_file_returns_empty(self, tmp_path: Path) -> None:
        """Empty file returns empty list."""
        f = tmp_path / "empty.txt"
        f.write_text("", encoding="utf-8")

        assert RecruiterNotesParser().parse(f) == []

    def test_nonexistent_file_raises_parse_error(self) -> None:
        """Missing file raises ParseError."""
        with pytest.raises(ParseError):
            RecruiterNotesParser().parse(Path("/nonexistent.txt"))
