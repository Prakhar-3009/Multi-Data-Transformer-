"""Abstract base class for source parsers.

The BaseParser defines the contract that every source parser must implement.
This enables the plugin/registry pattern: adding a new source type requires
implementing this interface and registering the parser — no changes to the
pipeline core.

Design decisions:
- parse() returns a list of raw dictionaries, not domain objects. The
  extractor layer (Stage 3b) is responsible for converting raw dicts into
  typed CandidateFragments. This separation keeps parsing (bytes → structure)
  decoupled from extraction (structure → domain object).
- All parsers catch their own exceptions and raise ParseError. The pipeline
  never sees a KeyError or JSONDecodeError from a parser.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from src.core.exceptions import ParseError


class BaseParser(ABC):
    """Abstract base class for all source parsers.

    Subclasses must implement `parse()` to convert a file into a list
    of raw record dictionaries.
    """

    @abstractmethod
    def parse(self, file_path: Path) -> list[dict]:
        """Parse a source file into a list of raw record dictionaries.

        Args:
            file_path: Path to the source file.

        Returns:
            List of raw record dictionaries. Each dict represents one
            candidate record from the source, with the source's own
            field names (not canonical names).

        Raises:
            ParseError: If the file cannot be read or parsed.
                        The pipeline catches this and degrades the
                        source to empty — it never crashes.
        """
        ...

    def safe_parse(self, file_path: Path) -> list[dict]:
        """Parse with graceful degradation — never raises.

        Catches all exceptions and returns an empty list on failure.
        This is the method the pipeline calls.

        Args:
            file_path: Path to the source file.

        Returns:
            List of raw record dicts, or empty list on failure.
        """
        try:
            return self.parse(file_path)
        except ParseError:
            raise  # Let ParseError propagate (pipeline handles it)
        except Exception as e:
            raise ParseError(
                f"Unexpected error parsing {file_path}: {e}",
                context={"file": str(file_path), "error": str(e)},
            ) from e
