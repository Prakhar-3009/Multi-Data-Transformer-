"""Parsers package — source-specific file parsers.

Each parser converts a raw file into a list of dictionaries.
The extraction layer (extractors) handles converting those dicts
into typed CandidateFragments.
"""

from src.parsers.csv_parser import RecruiterCSVParser
from src.parsers.json_parser import ATSJSONParser
from src.parsers.text_parser import RecruiterNotesParser

__all__ = [
    "RecruiterCSVParser",
    "ATSJSONParser",
    "RecruiterNotesParser",
]
