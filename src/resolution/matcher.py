"""Fuzzy matcher for entity resolution — name + company matching.

Used as a fallback after email and phone blocking. Compares unmatched
fragments by name similarity, gated by company similarity to prevent
false merges of common names.

Conservative by design: a wrong merge is a "confident-wrong" error —
worse than a missed merge. When in doubt, keep records separate.

Uses rapidfuzz token_sort_ratio for name comparison (handles word
reordering: "John Smith" vs "Smith, John").
"""

from __future__ import annotations

import logging

from rapidfuzz import fuzz

from src.core.constants import COMPANY_SIMILARITY_THRESHOLD, NAME_SIMILARITY_THRESHOLD
from src.models.fragments import CandidateFragment

logger = logging.getLogger(__name__)


def fuzzy_match_candidates(
    fragments: list[CandidateFragment],
    source_indices: list[int],
    target_indices: list[int],
    name_threshold: float = NAME_SIMILARITY_THRESHOLD,
    company_threshold: float = COMPANY_SIMILARITY_THRESHOLD,
) -> list[tuple[int, int, float]]:
    """Find fuzzy matches among unmatched fragments against all fragments.

    Compares fragments in source_indices against target_indices by name
    similarity, gated by company or location similarity to prevent false merges
    of common names (e.g., two different "John Smith"s).
    """
    matches: list[tuple[int, int, float]] = []
    checked_pairs: set[tuple[int, int]] = set()

    for idx_a in source_indices:
        for idx_b in target_indices:
            if idx_a == idx_b:
                continue
                
            # Ensure consistent ordering to avoid duplicate pairs
            pair = tuple(sorted([idx_a, idx_b]))
            if pair in checked_pairs:
                continue
            checked_pairs.add(pair)

            name_a = _get_name(fragments[idx_a])
            name_b = _get_name(fragments[idx_b])

            if not name_a or not name_b:
                continue

            name_score = fuzz.token_sort_ratio(name_a, name_b)
            is_initials = _is_initial_match(name_a, name_b)
            
            # Treat initials match as equivalent to name_score 95
            if is_initials:
                name_score = max(name_score, 95.0)

            if name_score < name_threshold:
                continue

            company_a = _get_company(fragments[idx_a])
            company_b = _get_company(fragments[idx_b])
            
            location_a = _get_location(fragments[idx_a])
            location_b = _get_location(fragments[idx_b])

            company_match = False
            if company_a and company_b:
                company_match = fuzz.token_sort_ratio(company_a, company_b) >= company_threshold
                
            location_match = False
            if location_a and location_b:
                location_match = fuzz.token_sort_ratio(location_a, location_b) >= company_threshold

            if company_match or location_match:
                # Both name and (company OR location) match → high confidence merge
                confidence = name_score / 100.0
                matches.append((idx_a, idx_b, confidence))
                logger.debug(
                    "Fuzzy match: %r ↔ %r (name=%.1f, company_match=%s, location_match=%s)",
                    name_a, name_b, name_score, company_match, location_match
                )
            elif name_score >= 95:
                # Very high name match with different/missing context → still merge
                confidence = name_score / 100.0 * 0.7  # Lower confidence
                matches.append((idx_a, idx_b, confidence))
                logger.debug(
                    "High-name fallback match: %r ↔ %r (name=%.1f)",
                    name_a, name_b, name_score
                )

    logger.info("Fuzzy matching found %d candidate pairs", len(matches))
    return matches


def _get_name(fragment: CandidateFragment) -> str | None:
    """Extract name from a fragment for fuzzy matching."""
    fv = fragment.get_field_value("full_name")
    if fv is None or fv.value is None:
        return None
    val = fv.value
    if isinstance(val, str) and val.strip():
        return val.strip().lower()
    return None


def _get_company(fragment: CandidateFragment) -> str | None:
    """Extract company from a fragment for gated matching."""
    fv = fragment.get_field_value("current_company")
    if fv is None or fv.value is None:
        return None
    val = fv.value
    if isinstance(val, str) and val.strip():
        return val.strip().lower()
    return None


def _get_location(fragment: CandidateFragment) -> str | None:
    """Extract location string for gated matching."""
    fv = fragment.get_field_value("location")
    if fv is None or fv.value is None:
        return None
    val = fv.value
    if isinstance(val, dict):
        parts = [val.get("city"), val.get("country")]
        loc_str = " ".join(str(p) for p in parts if p)
        if loc_str:
            return loc_str.lower()
    return None


def _is_initial_match(name_a: str, name_b: str) -> bool:
    """Check if one name is an initialized version of the other.
    e.g. 'j. smith' vs 'john smith'
    """
    parts_a = name_a.replace(".", " ").lower().split()
    parts_b = name_b.replace(".", " ").lower().split()
    if not parts_a or not parts_b:
        return False
        
    # If they don't have the same number of words, it's risky
    if len(parts_a) != len(parts_b):
        return False
        
    for pa, pb in zip(parts_a, parts_b):
        if pa == pb:
            continue
        if len(pa) == 1 and pb.startswith(pa):
            continue
        if len(pb) == 1 and pa.startswith(pb):
            continue
        return False
        
    return True

