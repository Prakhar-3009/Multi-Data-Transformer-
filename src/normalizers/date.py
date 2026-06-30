"""Date normalizer — validate-then-normalize to YYYY-MM format.

Handles varied date formats (Jan 2024, 01/2024, 2024-01, etc.) with
explicit guardrails against dateutil's over-eager defaulting. The
honesty principle is critical here:

- Year-only input ("2024") → "2024" with no fake month. Defaulting to
  January is the classic confident-wrong bug.
- "Present" / "Current" → None (not a date, it's a state).
- Unparseable → None. Never guess.

Strategy:
1. Try known explicit formats first (deterministic, no guessing)
2. Fall back to dateutil with strict extraction (month+year must be present)
3. Handle year-only as a special case
"""

from __future__ import annotations

import logging
import re
from datetime import datetime

from dateutil import parser as dateutil_parser

logger = logging.getLogger(__name__)

# Sentinel strings that mean "currently employed" — not a date
_CURRENT_SENTINELS = frozenset({
    "present", "current", "now", "ongoing", "till date", "to date",
    "till now", "to present",
})

# Explicit format patterns to try first, in priority order.
# These are deterministic — no guessing, no defaulting.
_EXPLICIT_FORMATS = [
    "%B %Y",      # January 2024
    "%b %Y",      # Jan 2024
    "%m/%Y",      # 01/2024
    "%Y-%m",      # 2024-01
    "%Y/%m",      # 2024/01
    "%m-%Y",      # 01-2024
    "%Y %B",      # 2024 January
    "%Y %b",      # 2024 Jan
    "%B, %Y",     # January, 2024
    "%b, %Y",     # Jan, 2024
    "%m.%Y",      # 01.2024
    "%Y.%m",      # 2024.01
]

# Regex for year-only input (4 digits, nothing else meaningful)
_YEAR_ONLY_RE = re.compile(r"^\s*(\d{4})\s*$")


def normalize_date(raw_date: str) -> tuple[str | None, float]:
    """Validate and normalize a date string to YYYY-MM format.

    Args:
        raw_date: Raw date string from any source.

    Returns:
        Tuple of (normalized_date, confidence):
        - Full date: ("2024-01", 1.0)
        - Year-only: ("2024", 0.8) — honest about missing month
        - Current/present: (None, 0.0)
        - Unparseable: (None, 0.0)

    Examples:
        >>> normalize_date("Jan 2024")
        ('2024-01', 1.0)
        >>> normalize_date("01/2024")
        ('2024-01', 1.0)
        >>> normalize_date("2024")
        ('2024', 0.8)
        >>> normalize_date("Present")
        (None, 0.0)
        >>> normalize_date("")
        (None, 0.0)
    """
    if not raw_date or not isinstance(raw_date, str):
        return None, 0.0

    cleaned = raw_date.strip()
    if not cleaned:
        return None, 0.0

    # Check for "present" / "current" sentinels
    if cleaned.lower() in _CURRENT_SENTINELS:
        return None, 0.0

    # Try explicit formats first — deterministic, no guessing
    for fmt in _EXPLICIT_FORMATS:
        try:
            dt = datetime.strptime(cleaned, fmt)
            return dt.strftime("%Y-%m"), 1.0
        except ValueError:
            continue

    # Check for year-only input — honest handling, no fake month
    year_match = _YEAR_ONLY_RE.match(cleaned)
    if year_match:
        year = int(year_match.group(1))
        if 1900 <= year <= 2100:
            # Return year-only with lower confidence — we're honest about
            # the missing month. This is a key talking point.
            return str(year), 0.8
        return None, 0.0

    # Fall back to dateutil with strict extraction
    try:
        # Pin defaults to avoid dateutil silently injecting today's date
        default_dt = datetime(1, 1, 1)
        dt = dateutil_parser.parse(cleaned, default=default_dt, fuzzy=True)

        # Only accept if both month and year were actually in the input.
        # If dateutil used our default (month=1, year=1), it invented values.
        if dt.year == 1 or dt.month == 1:
            # Could be real January or year 0001 — check if "jan" or the year
            # is actually in the input
            has_month = dt.month != 1 or _has_month_indicator(cleaned)
            has_year = dt.year != 1 or bool(re.search(r"\b\d{4}\b", cleaned))

            if has_year and has_month:
                return dt.strftime("%Y-%m"), 0.9
            elif has_year:
                return str(dt.year) if dt.year != 1 else re.search(r"\b(\d{4})\b", cleaned).group(1), 0.8
            return None, 0.0

        return dt.strftime("%Y-%m"), 0.9  # Slightly lower confidence for dateutil path

    except (ValueError, OverflowError):
        logger.debug("Date parse failed for: %r", raw_date)
        return None, 0.0


def _has_month_indicator(text: str) -> bool:
    """Check if the text contains a month name or month number indicator."""
    lower = text.lower()
    month_names = [
        "january", "february", "march", "april", "may", "june",
        "july", "august", "september", "october", "november", "december",
        "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "oct",
        "nov", "dec",
    ]
    return any(m in lower for m in month_names)
