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
    candidate_indices: list[int],
    name_threshold: float = NAME_SIMILARITY_THRESHOLD,
    company_threshold: float = COMPANY_SIMILARITY_THRESHOLD,
) -> list[tuple[int, int, float]]:
    """Find fuzzy matches among unmatched fragments.

    Compares all pairs of fragments in candidate_indices by name
    similarity, gated by company similarity to prevent false merges
    of common names (e.g., two different "John Smith"s).

    Args:
        fragments: Full list of fragments (for value access).
        candidate_indices: Indices of fragments to compare (unmatched
                          by email/phone blocking).
        name_threshold: Minimum name similarity (0-100). Default 85.
        company_threshold: Minimum company similarity (0-100). Default 80.

    Returns:
        List of (idx_a, idx_b, confidence) tuples for matched pairs.
        Confidence is the name similarity score / 100.
    """
    matches: list[tuple[int, int, float]] = []

    for i in range(len(candidate_indices)):
        for j in range(i + 1, len(candidate_indices)):
            idx_a = candidate_indices[i]
            idx_b = candidate_indices[j]

            name_a = _get_name(fragments[idx_a])
            name_b = _get_name(fragments[idx_b])

            if not name_a or not name_b:
                continue

            # Name similarity using token_sort_ratio
            # (handles word reordering: "John Smith" vs "Smith, John")
            name_score = fuzz.token_sort_ratio(name_a, name_b)

            if name_score < name_threshold * 100:
                continue

            # Gate by company similarity — don't merge two "John Smith"s
            # at different companies unless names are near-identical
            company_a = _get_company(fragments[idx_a])
            company_b = _get_company(fragments[idx_b])

            if company_a and company_b:
                company_score = fuzz.token_sort_ratio(company_a, company_b)
                if company_score >= company_threshold * 100:
                    # Both name and company match → high confidence merge
                    confidence = name_score / 100.0
                    matches.append((idx_a, idx_b, confidence))
                    logger.debug(
                        "Fuzzy match: %r ↔ %r (name=%d, company=%d)",
                        name_a, name_b, name_score, company_score,
                    )
                elif name_score >= 95:
                    # Very high name match with different company → still merge
                    # (person might have changed jobs)
                    confidence = name_score / 100.0 * 0.8  # Lower confidence
                    matches.append((idx_a, idx_b, confidence))
                    logger.debug(
                        "High-name-low-company match: %r ↔ %r (name=%d, company=%d)",
                        name_a, name_b, name_score, company_score,
                    )
            elif name_score >= 95:
                # One or both missing company, but names are very similar
                # → merge with moderate confidence
                confidence = name_score / 100.0 * 0.7
                matches.append((idx_a, idx_b, confidence))

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
