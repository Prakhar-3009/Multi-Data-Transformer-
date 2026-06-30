"""Phone number normalizer — validate-then-normalize to E.164 format.

Uses Google's libphonenumber (phonenumbers library) for parsing and
validation. NEVER hand-rolls phone logic with regex — phone numbering
plans have thousands of edge cases (variable lengths, area codes, trunk
prefixes per country), and a regex will be confidently wrong.

Design:
- Parse with default region (configurable, defaults to "IN")
- Validate with is_valid_number() — the semantic validation gate
- Format to E.164 on success
- Return None on any failure — never guess a format

The validate-then-normalize is atomic: we don't normalize a value
we can't validate, and we don't validate without normalizing.
"""

from __future__ import annotations

import logging

import phonenumbers

from src.core.constants import DEFAULT_PHONE_REGION

logger = logging.getLogger(__name__)


def normalize_phone(
    raw_phone: str,
    default_region: str = DEFAULT_PHONE_REGION,
) -> tuple[str | None, float]:
    """Validate and normalize a phone number to E.164 format.

    Args:
        raw_phone: Raw phone string from any source. May contain spaces,
                   dashes, parentheses, country codes, or trunk prefixes.
        default_region: ISO 3166-1 alpha-2 country code for resolving
                        numbers without an explicit country code.

    Returns:
        Tuple of (normalized_phone, confidence):
        - On success: ("+919876543210", 1.0)
        - On validation failure: (None, 0.0)
        - On parse error: (None, 0.0)

    Examples:
        >>> normalize_phone("9876543210")
        ('+919876543210', 1.0)
        >>> normalize_phone("+1 (555) 123-4567", "US")
        ('+15551234567', 1.0)
        >>> normalize_phone("invalid")
        (None, 0.0)
        >>> normalize_phone("")
        (None, 0.0)
    """
    if not raw_phone or not isinstance(raw_phone, str):
        return None, 0.0

    cleaned = raw_phone.strip()
    if not cleaned:
        return None, 0.0

    try:
        parsed = phonenumbers.parse(cleaned, default_region)
    except phonenumbers.NumberParseException:
        logger.debug(
            "Phone parse failed: %r (region=%s)", raw_phone, default_region
        )
        return None, 0.0

    # Semantic validation — is this a real, assignable phone number?
    if not phonenumbers.is_valid_number(parsed):
        logger.debug(
            "Phone validation failed: %r parsed but not valid", raw_phone
        )
        return None, 0.0

    # Format to E.164 — the single canonical form
    e164 = phonenumbers.format_number(
        parsed, phonenumbers.PhoneNumberFormat.E164
    )

    return e164, 1.0
