"""ATS JSON parser — handles the schema-mismatched structured source.

The ATS JSON is structured and machine-readable, but its field names
deliberately don't match the canonical schema. Parsing is trivial
(json.load), but the shape can vary:
- Single candidate dict
- Array of candidate dicts  
- Nested structure with candidates under a key

This parser handles all three shapes defensively, using safe nested
access to avoid KeyError crashes on unexpected structures.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from src.core.exceptions import ParseError
from src.parsers.base import BaseParser

logger = logging.getLogger(__name__)


class ATSJSONParser(BaseParser):
    """Parser for ATS JSON export files.

    Handles multiple JSON shapes (single object, array, nested) and
    provides defensive access. Returns raw dicts with the ATS's own
    field names — the extractor handles the mapping to canonical names.
    """

    def parse(self, file_path: Path) -> list[dict]:
        """Parse an ATS JSON file into a list of candidate dicts.

        Args:
            file_path: Path to the JSON file.

        Returns:
            List of raw candidate dicts with ATS field names.

        Raises:
            ParseError: If the file cannot be read or contains invalid JSON.
        """
        if not file_path.exists():
            raise ParseError(
                f"JSON file not found: {file_path}",
                context={"file": str(file_path)},
            )

        try:
            raw_text = file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            try:
                raw_text = file_path.read_text(encoding="latin-1")
            except Exception as e:
                raise ParseError(
                    f"Cannot read JSON file {file_path}: {e}",
                    context={"file": str(file_path)},
                ) from e

        if not raw_text.strip():
            logger.warning("JSON file is empty: %s", file_path)
            return []

        try:
            data = json.loads(raw_text)
        except json.JSONDecodeError as e:
            raise ParseError(
                f"Invalid JSON in {file_path}: {e}",
                context={"file": str(file_path), "error": str(e)},
            ) from e

        records = self._extract_records(data, file_path)
        logger.info("Parsed %d records from JSON: %s", len(records), file_path)
        return records

    def _extract_records(self, data: object, file_path: Path) -> list[dict]:
        """Extract candidate records from various JSON shapes.

        Handles:
        - List of dicts: [{...}, {...}] → return as-is
        - Single dict with candidate data: {...} → wrap in list
        - Nested dict with candidates key: {"candidates": [...]} → unwrap

        Args:
            data: Parsed JSON data (any shape).
            file_path: Source file path (for logging).

        Returns:
            List of candidate dicts.
        """
        if isinstance(data, list):
            # Shape: [{candidate1}, {candidate2}, ...]
            return [r for r in data if isinstance(r, dict)]

        if isinstance(data, dict):
            # Shape: nested with a known candidates key
            for key in ("candidates", "applicants", "records", "data", "results"):
                if key in data and isinstance(data[key], list):
                    logger.debug("Found candidates under '%s' key", key)
                    return [r for r in data[key] if isinstance(r, dict)]

            # Shape: single candidate dict
            # Heuristic: if it has candidate-like fields, treat as single record
            candidate_signals = {
                "name", "email", "phone", "candidate_name", "applicant_name",
                "contact_email", "full_name",
            }
            if any(k in data for k in candidate_signals):
                return [data]

            # Unknown shape — log and return empty
            logger.warning(
                "Unrecognized JSON structure in %s (keys: %s)",
                file_path, list(data.keys())[:10],
            )
            return []

        logger.warning(
            "JSON root is neither dict nor list in %s: %s",
            file_path, type(data).__name__,
        )
        return []
