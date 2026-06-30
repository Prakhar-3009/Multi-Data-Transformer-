"""Country normalizer — name/code → ISO 3166-1 alpha-2.

Uses pycountry for robust resolution of country names, alpha-2 codes,
alpha-3 codes, and common variations to the standard ISO 3166-1 alpha-2
format (e.g., "US", "IN", "DE").

Handles:
- Already valid alpha-2: "US" → "US"
- Alpha-3: "USA" → "US"
- Full names: "United States" → "US"
- Common variations: "India" → "IN"
- Invalid/unknown → None (never guess)
"""

from __future__ import annotations

import logging

import pycountry

logger = logging.getLogger(__name__)

# Common informal names that pycountry may not resolve directly
_COMMON_ALIASES: dict[str, str] = {
    "usa": "US",
    "u.s.a.": "US",
    "u.s.": "US",
    "united states of america": "US",
    "united states": "US",
    "america": "US",
    "uk": "GB",
    "u.k.": "GB",
    "united kingdom": "GB",
    "great britain": "GB",
    "england": "GB",
    "india": "IN",
    "germany": "DE",
    "france": "FR",
    "canada": "CA",
    "australia": "AU",
    "japan": "JP",
    "china": "CN",
    "brazil": "BR",
    "south korea": "KR",
    "korea": "KR",
    "singapore": "SG",
    "netherlands": "NL",
    "holland": "NL",
    "sweden": "SE",
    "switzerland": "CH",
    "israel": "IL",
    "ireland": "IE",
    "spain": "ES",
    "italy": "IT",
    "russia": "RU",
    "uae": "AE",
    "united arab emirates": "AE",
}


def normalize_country(raw_country: str) -> tuple[str | None, float]:
    """Normalize a country name or code to ISO 3166-1 alpha-2.

    Args:
        raw_country: Raw country string (name, alpha-2, alpha-3, etc.).

    Returns:
        Tuple of (iso_alpha2, confidence):
        - Exact code match: ("US", 1.0)
        - Name/alias resolved: ("IN", 0.95)
        - Unknown: (None, 0.0)

    Examples:
        >>> normalize_country("US")
        ('US', 1.0)
        >>> normalize_country("USA")
        ('US', 1.0)
        >>> normalize_country("India")
        ('IN', 0.95)
        >>> normalize_country("Freedonia")
        (None, 0.0)
    """
    if not raw_country or not isinstance(raw_country, str):
        return None, 0.0

    cleaned = raw_country.strip()
    if not cleaned:
        return None, 0.0

    upper = cleaned.upper()

    # Check if already a valid alpha-2 code
    if len(upper) == 2:
        country = pycountry.countries.get(alpha_2=upper)
        if country:
            return country.alpha_2, 1.0

    # Check if alpha-3 code
    if len(upper) == 3:
        country = pycountry.countries.get(alpha_3=upper)
        if country:
            return country.alpha_2, 1.0

    # Check common aliases first (faster than pycountry fuzzy search)
    lower = cleaned.lower().strip()
    if lower in _COMMON_ALIASES:
        return _COMMON_ALIASES[lower], 0.95

    # Try pycountry name lookup
    try:
        country = pycountry.countries.lookup(cleaned)
        return country.alpha_2, 0.95
    except LookupError:
        pass

    # Try fuzzy search as last resort
    try:
        results = pycountry.countries.search_fuzzy(cleaned)
        if results:
            return results[0].alpha_2, 0.85
    except LookupError:
        pass

    logger.debug("Country normalization failed: %r", raw_country)
    return None, 0.0
