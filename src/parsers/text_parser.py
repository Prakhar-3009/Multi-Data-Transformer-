"""Recruiter notes text parser — handles free-text unstructured source.



This parser's main job is:
1. Read the file with encoding fallback
2. Normalize whitespace (collapse copy-paste artifacts)
3. Split into per-candidate blocks if the file contains multiple candidates
   (assumption: each candidate is separated by a blank line or marker)
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from src.core.exceptions import ParseError
from src.parsers.base import BaseParser

logger = logging.getLogger(__name__)

# Separators that might divide multiple candidates in one file
_CANDIDATE_SEPARATORS = re.compile(
    r"\n\s*(?:---+|===+|___+|\*\*\*+)\s*\n"  # Horizontal rules
    r"|\n\s*candidate\s*(?:\d+|#\d+)\s*:?\s*\n",  # "Candidate 1:", etc.
    re.IGNORECASE,
)


class RecruiterNotesParser(BaseParser):
    """Parser for recruiter notes text files.

    Returns a list of dicts, each containing the raw text block for
    one candidate. The extractor handles regex-based field extraction.
    """

    def parse(self, file_path: Path) -> list[dict]:
        """Parse a recruiter notes text file.

        Args:
            file_path: Path to the .txt file.

        Returns:
            List of dicts with key "raw_text" containing the text block.
            Usually one element (one candidate per file), but supports
            multi-candidate files separated by dividers.

        Raises:
            ParseError: If the file cannot be read.
        """
        if not file_path.exists():
            raise ParseError(
                f"Text file not found: {file_path}",
                context={"file": str(file_path)},
            )

        raw_text = self._read_with_fallback(file_path)
        if not raw_text.strip():
            logger.warning("Text file is empty: %s", file_path)
            return []

        # Normalize whitespace artifacts (tabs, multiple spaces, \r)
        cleaned = self._normalize_whitespace(raw_text)

        # Split into candidate blocks
        blocks = self._split_candidates(cleaned)

        records = []
        for i, block in enumerate(blocks):
            text = block.strip()
            if not text:
                continue
            records.append({
                "raw_text": text,
                "block_index": i,
                "source_file": str(file_path),
            })

        logger.info(
            "Parsed %d candidate block(s) from notes: %s",
            len(records), file_path,
        )
        return records

    def _read_with_fallback(self, file_path: Path) -> str:
        """Read text file with encoding fallback."""
        for encoding in ("utf-8", "utf-8-sig", "latin-1", "cp1252"):
            try:
                return file_path.read_text(encoding=encoding)
            except UnicodeDecodeError:
                continue

        logger.warning("All encodings failed for %s", file_path)
        return file_path.read_text(encoding="utf-8", errors="replace")

    @staticmethod
    def _normalize_whitespace(text: str) -> str:
        """Normalize whitespace: collapse runs, strip \r, normalize tabs."""
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        text = text.replace("\t", " ")
        # Collapse multiple spaces (but preserve newlines for structure)
        text = re.sub(r"[^\S\n]+", " ", text)
        return text

    @staticmethod
    def _split_candidates(text: str) -> list[str]:
        """Split text into per-candidate blocks using separator patterns."""
        blocks = _CANDIDATE_SEPARATORS.split(text)
        # If no separators found, treat entire text as one candidate
        if len(blocks) <= 1:
            return [text]
        return blocks
