"""Email normalizer — validate-then-normalize.

Emails are the strongest match key in entity resolution, so correctness
here directly impacts merge quality. Rules:

- Lowercase entire address (case-insensitive in practice for all major
  providers — lowercasing makes them comparable).
- Validate structure with regex (not perfect, but catches obvious garbage
  like "john@", "nogmail", missing TLD).
- Dedup and sort within a candidate for determinism.
- Invalid → null the value, don't drop the record.
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# RFC 5322 simplified email regex — catches the vast majority of real emails
# while rejecting obvious garbage. Not trying to be RFC-perfect (that regex
# is 6,000+ characters), just good enough for validation.
_EMAIL_RE = re.compile(
    r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$"
)


def normalize_email(raw_email: str) -> tuple[str | None, float]:
    """Validate and normalize an email address.

    Args:
        raw_email: Raw email string from any source.

    Returns:
        Tuple of (normalized_email, confidence):
        - Valid: ("john@example.com", 1.0)
        - Invalid: (None, 0.0)

    Examples:
        >>> normalize_email("John@Example.COM")
        ('john@example.com', 1.0)
        >>> normalize_email("  user@domain.org  ")
        ('user@domain.org', 1.0)
        >>> normalize_email("john@")
        (None, 0.0)
        >>> normalize_email("")
        (None, 0.0)
    """
    if not raw_email or not isinstance(raw_email, str):
        return None, 0.0

    cleaned = raw_email.strip().lower()
    if not cleaned:
        return None, 0.0

    if not _EMAIL_RE.match(cleaned):
        logger.debug("Email validation failed: %r", raw_email)
        return None, 0.0

    return cleaned, 1.0


def normalize_email_list(raw_emails: list[str]) -> list[str]:
    """Normalize, validate, deduplicate, and sort a list of emails.

    Invalid emails are silently dropped. The resulting list is:
    - Lowercased
    - Deduplicated (case-insensitive)
    - Sorted (deterministic ordering, so [0] is stable)

    Args:
        raw_emails: List of raw email strings.

    Returns:
        Sorted, deduplicated list of valid normalized emails.
    """
    seen: set[str] = set()
    result: list[str] = []

    for raw in raw_emails:
        normalized, _ = normalize_email(raw)
        if normalized is not None and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)

    return sorted(result)
