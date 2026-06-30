"""CSV parser — Recruiter CSV source.

Uses stdlib csv.DictReader (not pandas) for zero-dependency, predictable
parsing. Handles common CSV edge cases:
- Delimiter sniffing (comma, semicolon, tab)
- Encoding fallback (UTF-8 → Latin-1 → errors='replace')
- Empty/whitespace-only rows skipped
- Duplicate rows detected via row hash
"""

from __future__ import annotations

import csv
import hashlib
import io
import logging
from pathlib import Path

from src.core.exceptions import ParseError
from src.parsers.base import BaseParser

logger = logging.getLogger(__name__)

# Encodings to try in order
_ENCODINGS = ["utf-8", "utf-8-sig", "latin-1", "cp1252"]


class RecruiterCSVParser(BaseParser):
    """Parser for recruiter-exported CSV files.

    Handles delimiter detection, encoding fallback, empty row skipping,
    and row-level deduplication. Returns one dict per valid row.
    """

    def parse(self, file_path: Path) -> list[dict]:
        """Parse a CSV file into a list of row dictionaries.

        Args:
            file_path: Path to the CSV file.

        Returns:
            List of dicts, one per valid row. Keys are column headers
            (stripped, lowercased). Empty/whitespace-only values are
            converted to None.

        Raises:
            ParseError: If the file cannot be read or parsed at all.
        """
        if not file_path.exists():
            raise ParseError(
                f"CSV file not found: {file_path}",
                context={"file": str(file_path)},
            )

        raw_text = self._read_with_fallback(file_path)
        if not raw_text.strip():
            logger.warning("CSV file is empty: %s", file_path)
            return []

        delimiter = self._detect_delimiter(raw_text)
        reader = csv.DictReader(
            io.StringIO(raw_text), delimiter=delimiter
        )

        records: list[dict] = []
        seen_hashes: set[str] = set()
        row_num = 0

        for row in reader:
            row_num += 1
            try:
                # Normalize keys: strip whitespace, lowercase
                cleaned = self._clean_row(row)

                # Skip completely empty rows
                if not any(cleaned.values()):
                    continue

                # Dedup by row content hash
                row_hash = self._hash_row(cleaned)
                if row_hash in seen_hashes:
                    logger.debug("Duplicate row %d skipped in %s", row_num, file_path)
                    continue
                seen_hashes.add(row_hash)

                records.append(cleaned)

            except Exception as e:
                # Bad row → skip row, continue with rest
                logger.warning(
                    "Skipping malformed row %d in %s: %s", row_num, file_path, e
                )
                continue

        logger.info("Parsed %d records from CSV: %s", len(records), file_path)
        return records

    def _read_with_fallback(self, file_path: Path) -> str:
        """Read file with encoding fallback chain."""
        for encoding in _ENCODINGS:
            try:
                return file_path.read_text(encoding=encoding)
            except UnicodeDecodeError:
                logger.debug(
                    "Encoding %s failed for %s, trying next", encoding, file_path
                )
                continue

        # Last resort: replace errors
        logger.warning("All encodings failed for %s, using errors='replace'", file_path)
        return file_path.read_text(encoding="utf-8", errors="replace")

    def _detect_delimiter(self, text: str) -> str:
        """Detect CSV delimiter using csv.Sniffer, default to comma."""
        try:
            # Sample first 4KB for sniffing
            sample = text[:4096]
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
            return dialect.delimiter
        except csv.Error:
            return ","

    @staticmethod
    def _clean_row(row: dict) -> dict:
        """Normalize a row: strip/lowercase keys, empty strings → None."""
        cleaned = {}
        for key, value in row.items():
            if key is None:
                continue
            clean_key = key.strip().lower()
            if not clean_key:
                continue
            # Empty/whitespace-only values → None
            if value is None or (isinstance(value, str) and not value.strip()):
                cleaned[clean_key] = None
            else:
                cleaned[clean_key] = value.strip() if isinstance(value, str) else value
        return cleaned

    @staticmethod
    def _hash_row(row: dict) -> str:
        """Deterministic hash of row content for deduplication."""
        # Sort keys for determinism, then hash the repr
        content = "|".join(
            f"{k}={v}" for k, v in sorted(row.items()) if v is not None
        )
        return hashlib.md5(content.encode("utf-8")).hexdigest()
