"""Blocking strategy for entity resolution.

Blocking is the standard technique to avoid O(n²) pairwise comparisons.
Instead of comparing every fragment to every other fragment, we group
fragments into "blocks" by high-confidence match keys (email, phone).
Only fragments in the same block are compared.

Strategy (in priority order):
1. Block on normalized email (hash lookup, O(1) per fragment) — strongest key
2. Block on normalized phone (hash lookup) — second strongest
3. Remaining unmatched fragments go to fuzzy matching (Stage 5b)

This reduces the comparison space from O(n²) to approximately O(n).
"""

from __future__ import annotations

import logging
from collections import defaultdict

from src.models.fragments import CandidateFragment

logger = logging.getLogger(__name__)


def block_by_email(
    fragments: list[CandidateFragment],
) -> tuple[dict[str, list[int]], set[int]]:
    """Block fragments by normalized email address.

    Fragments with the same email are placed in the same block.
    Email is the strongest match key — near-unique to a person.

    Args:
        fragments: List of all candidate fragments.

    Returns:
        Tuple of:
        - blocks: Dict mapping email → list of fragment indices
        - matched_indices: Set of fragment indices that were matched

    Example:
        If fragments[0] and fragments[3] both have email "john@x.com",
        blocks = {"john@x.com": [0, 3]}, matched = {0, 3}
    """
    blocks: dict[str, list[int]] = defaultdict(list)
    matched: set[int] = set()

    for idx, fragment in enumerate(fragments):
        emails = _get_emails(fragment)
        for email in emails:
            blocks[email].append(idx)
            matched.add(idx)

    # Only keep blocks with >1 fragment (actual matches)
    multi_blocks = {k: v for k, v in blocks.items() if len(v) > 1}
    matched_in_multi = set()
    for indices in multi_blocks.values():
        matched_in_multi.update(indices)

    logger.debug(
        "Email blocking: %d blocks with %d matched fragments",
        len(multi_blocks), len(matched_in_multi),
    )
    return multi_blocks, matched_in_multi


def block_by_phone(
    fragments: list[CandidateFragment],
    already_matched: set[int] | None = None,
) -> tuple[dict[str, list[int]], set[int]]:
    """Block fragments by normalized phone number.

    Similar to email blocking but with phone as the key.
    Can optionally skip already-matched fragments.

    Args:
        fragments: List of all candidate fragments.
        already_matched: Indices already matched by email blocking.

    Returns:
        Tuple of (phone blocks, newly matched indices).
    """
    blocks: dict[str, list[int]] = defaultdict(list)
    matched: set[int] = set()

    for idx, fragment in enumerate(fragments):
        phones = _get_phones(fragment)
        for phone in phones:
            blocks[phone].append(idx)
            matched.add(idx)

    multi_blocks = {k: v for k, v in blocks.items() if len(v) > 1}
    new_matched = set()
    for indices in multi_blocks.values():
        new_matched.update(indices)

    logger.debug(
        "Phone blocking: %d blocks with %d matched fragments",
        len(multi_blocks), len(new_matched),
    )
    return multi_blocks, new_matched


def _get_emails(fragment: CandidateFragment) -> list[str]:
    """Extract normalized email(s) from a fragment for blocking."""
    fv = fragment.get_field_value("emails")
    if fv is None or fv.value is None:
        return []
    val = fv.value
    if isinstance(val, str):
        return [val.lower().strip()] if val.strip() else []
    if isinstance(val, list):
        return [e.lower().strip() for e in val if isinstance(e, str) and e.strip()]
    return []


def _get_phones(fragment: CandidateFragment) -> list[str]:
    """Extract normalized phone(s) from a fragment for blocking."""
    fv = fragment.get_field_value("phones")
    if fv is None or fv.value is None:
        return []
    val = fv.value
    if isinstance(val, str):
        return [val.strip()] if val.strip() else []
    if isinstance(val, list):
        return [p.strip() for p in val if isinstance(p, str) and p.strip()]
    return []
