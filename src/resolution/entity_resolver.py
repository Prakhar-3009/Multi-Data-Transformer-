"""Entity resolver — the full resolution pipeline.

Orchestrates blocking, fuzzy matching, and Union-Find to cluster
candidate fragments that refer to the same person.

Pipeline:
1. Block on email (O(n)) → merge clusters via Union-Find
2. Block on phone (O(n)) → merge clusters via Union-Find
3. Fuzzy match remaining unmatched (name + company gating) → merge clusters
4. Return final clusters via Union-Find transitive closure

The Union-Find ensures transitivity: if A=B (email) and B=C (phone),
then A, B, C are all in the same cluster.
"""

from __future__ import annotations

import logging

from src.models.fragments import CandidateFragment
from src.resolution.blocking import block_by_email, block_by_phone
from src.resolution.matcher import fuzzy_match_candidates
from src.resolution.union_find import UnionFind

logger = logging.getLogger(__name__)


def resolve_entities(
    fragments: list[CandidateFragment],
) -> list[list[int]]:
    """Cluster fragments that refer to the same person.

    Uses a three-stage strategy:
    1. Email blocking (strongest signal)
    2. Phone blocking (second signal)
    3. Fuzzy name + company matching (fallback for unmatched)

    All stages feed into a single Union-Find for transitive closure.

    Args:
        fragments: List of all candidate fragments from all sources.

    Returns:
        List of clusters, where each cluster is a list of fragment
        indices that refer to the same person. Sorted deterministically
        (by smallest index in each cluster, then by index within cluster).
    """
    if not fragments:
        return []

    n = len(fragments)
    uf = UnionFind()

    # Initialize all fragments as their own set
    for i in range(n):
        uf.find(i)

    all_matched: set[int] = set()

    # Stage 1: Block by email (strongest match key)
    email_blocks, email_matched = block_by_email(fragments)
    for email, indices in email_blocks.items():
        for i in range(1, len(indices)):
            uf.union(indices[0], indices[i])
        all_matched.update(indices)

    logger.info("After email blocking: %d fragments matched", len(all_matched))

    # Stage 2: Block by phone (second match key)
    phone_blocks, phone_matched = block_by_phone(fragments)
    for phone, indices in phone_blocks.items():
        for i in range(1, len(indices)):
            uf.union(indices[0], indices[i])
        all_matched.update(indices)

    logger.info(
        "After phone blocking: %d total fragments matched",
        len(all_matched),
    )

    # Stage 3: Fuzzy matching on remaining unmatched fragments
    unmatched = [i for i in range(n) if i not in all_matched]
    if unmatched:
        fuzzy_matches = fuzzy_match_candidates(fragments, unmatched)
        for idx_a, idx_b, confidence in fuzzy_matches:
            uf.union(idx_a, idx_b)
            all_matched.update([idx_a, idx_b])

        logger.info(
            "After fuzzy matching: %d additional pairs merged",
            len(fuzzy_matches),
        )

    # Build final clusters from Union-Find
    all_indices = list(range(n))
    raw_clusters = uf.get_clusters(all_indices)

    # Sort clusters deterministically:
    # - Clusters ordered by their smallest member index
    # - Members within each cluster sorted by index
    clusters = [sorted(members) for members in raw_clusters.values()]
    clusters.sort(key=lambda c: c[0])

    logger.info(
        "Entity resolution complete: %d fragments → %d candidates",
        n, len(clusters),
    )

    return clusters
