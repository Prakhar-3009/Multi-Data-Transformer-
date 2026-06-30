"""Abstract base class for field extractors.

Extractors take parsed data structures (from parsers) and produce
CandidateFragments — typed, tagged field values with provenance metadata.
This is where provenance is BORN: every field gets tagged with its source,
extraction method, and initial confidence.

The BaseExtractor defines the plugin interface: implement extract() to
convert a raw record dict into a list of CandidateFragments.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

from src.core.exceptions import ExtractionError
from src.models.fragments import CandidateFragment

logger = logging.getLogger(__name__)


class BaseExtractor(ABC):
    """Abstract base class for all field extractors.

    Subclasses must implement `extract()` to convert raw parsed records
    into CandidateFragments with tagged field values.
    """

    @abstractmethod
    def extract(self, raw_records: list[dict]) -> list[CandidateFragment]:
        """Extract candidate fragments from parsed records.

        Args:
            raw_records: List of raw record dicts from the parser.

        Returns:
            List of CandidateFragments, one per candidate found.
            Each fragment carries tagged FieldValues with source,
            method, and initial confidence.

        Raises:
            ExtractionError: If extraction fails for a record.
                             Individual record failures should be
                             caught and logged, not propagated.
        """
        ...

    def safe_extract(self, raw_records: list[dict]) -> list[CandidateFragment]:
        """Extract with graceful degradation — logs errors, never raises.

        Args:
            raw_records: List of raw record dicts from the parser.

        Returns:
            List of CandidateFragments. May be shorter than input
            if some records failed extraction.
        """
        try:
            return self.extract(raw_records)
        except ExtractionError:
            raise
        except Exception as e:
            logger.error("Unexpected extraction error: %s", e)
            raise ExtractionError(
                f"Extraction failed: {e}",
                context={"error": str(e)},
            ) from e
