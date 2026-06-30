"""Tests for entity resolution — blocking, fuzzy matching, Union-Find, merge.

Tests the cross-record stage: clustering fragments that refer to the
same person and merging them into canonical records.
"""

from __future__ import annotations

import pytest

from src.models.enums import ExtractionMethod, SourceType
from src.models.fields import FieldValue
from src.models.fragments import CandidateFragment
from src.resolution.blocking import block_by_email, block_by_phone
from src.resolution.entity_resolver import resolve_entities
from src.resolution.merge import merge_cluster
from src.resolution.union_find import UnionFind


def _make_fragment(
    source: SourceType,
    fields: dict[str, object],
    trust: float = 0.9,
) -> CandidateFragment:
    """Helper to create a CandidateFragment for testing."""
    fvs = {}
    for name, value in fields.items():
        fvs[name] = FieldValue(
            value=value,
            source=source,
            method=ExtractionMethod.DIRECT_FIELD_READ,
            confidence=0.95,
        )
    return CandidateFragment(source=source, source_trust=trust, fields=fvs)


class TestUnionFind:
    """Tests for Union-Find data structure."""

    def test_basic_union_and_find(self) -> None:
        uf = UnionFind()
        assert uf.find(0) == 0
        assert not uf.connected(0, 1)
        uf.union(0, 1)
        assert uf.connected(0, 1)

    def test_transitive_closure(self) -> None:
        """If A=B and B=C, then A=C."""
        uf = UnionFind()
        uf.union(0, 1)
        uf.union(1, 2)
        assert uf.connected(0, 2)

    def test_get_clusters(self) -> None:
        uf = UnionFind()
        uf.union(0, 1)
        uf.union(2, 3)
        clusters = uf.get_clusters([0, 1, 2, 3, 4])
        assert len(clusters) == 3  # {0,1}, {2,3}, {4}

    def test_idempotent_union(self) -> None:
        """Union of already-connected elements returns False."""
        uf = UnionFind()
        assert uf.union(0, 1) is True
        assert uf.union(0, 1) is False


class TestBlocking:
    """Tests for email and phone blocking."""

    def test_email_blocking(self) -> None:
        """Fragments with same email are in the same block."""
        fragments = [
            _make_fragment(SourceType.CSV, {"emails": ["john@test.com"]}),
            _make_fragment(SourceType.ATS_JSON, {"emails": ["john@test.com"]}),
            _make_fragment(SourceType.CSV, {"emails": ["jane@test.com"]}),
        ]
        blocks, matched = block_by_email(fragments)
        assert "john@test.com" in blocks
        assert set(blocks["john@test.com"]) == {0, 1}

    def test_phone_blocking(self) -> None:
        """Fragments with same phone are in the same block."""
        fragments = [
            _make_fragment(SourceType.CSV, {"phones": ["+919876543210"]}),
            _make_fragment(SourceType.ATS_JSON, {"phones": ["+919876543210"]}),
        ]
        blocks, matched = block_by_phone(fragments)
        assert len(blocks) == 1

    def test_no_blocking_on_different_values(self) -> None:
        """Different emails don't block together."""
        fragments = [
            _make_fragment(SourceType.CSV, {"emails": ["a@test.com"]}),
            _make_fragment(SourceType.ATS_JSON, {"emails": ["b@test.com"]}),
        ]
        blocks, _ = block_by_email(fragments)
        assert len(blocks) == 0  # No multi-blocks


class TestEntityResolver:
    """Tests for the full entity resolution pipeline."""

    def test_same_email_merged(self) -> None:
        """Fragments with matching email are clustered together."""
        fragments = [
            _make_fragment(SourceType.CSV, {
                "full_name": "John Smith", "emails": ["john@test.com"],
            }),
            _make_fragment(SourceType.ATS_JSON, {
                "full_name": "John Smith", "emails": ["john@test.com"],
            }),
        ]
        clusters = resolve_entities(fragments)
        assert len(clusters) == 1
        assert sorted(clusters[0]) == [0, 1]

    def test_different_email_not_merged(self) -> None:
        """Fragments with different emails stay separate."""
        fragments = [
            _make_fragment(SourceType.CSV, {
                "full_name": "John Smith", "emails": ["john@test.com"],
            }),
            _make_fragment(SourceType.ATS_JSON, {
                "full_name": "Jane Doe", "emails": ["jane@test.com"],
            }),
        ]
        clusters = resolve_entities(fragments)
        assert len(clusters) == 2

    def test_transitive_merge(self) -> None:
        """A=B (email) and B=C (phone) → A, B, C in same cluster."""
        fragments = [
            _make_fragment(SourceType.CSV, {
                "full_name": "John", "emails": ["john@test.com"],
            }),
            _make_fragment(SourceType.ATS_JSON, {
                "full_name": "John", "emails": ["john@test.com"],
                "phones": ["+919876543210"],
            }),
            _make_fragment(SourceType.RECRUITER_NOTES, {
                "full_name": "John", "phones": ["+919876543210"],
            }),
        ]
        clusters = resolve_entities(fragments)
        assert len(clusters) == 1
        assert sorted(clusters[0]) == [0, 1, 2]

    def test_empty_fragments(self) -> None:
        """Empty fragment list returns empty clusters."""
        assert resolve_entities([]) == []


class TestMergeCluster:
    """Tests for the merge engine."""

    def test_single_fragment_merge(self) -> None:
        """Single fragment becomes a canonical record."""
        fragments = [
            _make_fragment(SourceType.CSV, {
                "full_name": "John Smith",
                "emails": ["john@test.com"],
                "current_company": "Google",
            }),
        ]
        record = merge_cluster(fragments)
        assert record.full_name == "John Smith"
        assert "john@test.com" in record.emails
        assert record.current_company == "Google"
        assert record.candidate_id  # Not empty

    def test_multi_source_merge_picks_highest_trust(self) -> None:
        """CSV (trust=0.95) beats notes (trust=0.60) for scalar fields."""
        fragments = [
            _make_fragment(SourceType.CSV, {
                "full_name": "John Smith", "current_company": "Google",
            }, trust=0.95),
            _make_fragment(SourceType.RECRUITER_NOTES, {
                "full_name": "John Smith", "current_company": "Google Inc",
            }, trust=0.60),
        ]
        record = merge_cluster(fragments)
        # CSV should win (higher trust × confidence)
        assert record.current_company == "Google"

    def test_email_union(self) -> None:
        """Emails from multiple sources are unioned."""
        fragments = [
            _make_fragment(SourceType.CSV, {"emails": ["john@test.com"]}),
            _make_fragment(SourceType.ATS_JSON, {"emails": ["john.smith@work.com"]}),
        ]
        record = merge_cluster(fragments)
        assert len(record.emails) == 2
        assert "john@test.com" in record.emails
        assert "john.smith@work.com" in record.emails

    def test_skills_union(self) -> None:
        """Skills from multiple sources are unioned by name."""
        fragments = [
            _make_fragment(SourceType.CSV, {"skills": ["Python", "Java"]}),
            _make_fragment(SourceType.ATS_JSON, {"skills": ["Python", "SQL"]}),
        ]
        record = merge_cluster(fragments)
        skill_names = [s.name for s in record.skills]
        assert "Python" in skill_names
        assert "Java" in skill_names
        assert "SQL" in skill_names

    def test_provenance_generated(self) -> None:
        """Provenance entries are generated for merged scalar fields."""
        fragments = [
            _make_fragment(SourceType.CSV, {"full_name": "John Smith"}),
            _make_fragment(SourceType.ATS_JSON, {"full_name": "John Smith"}),
        ]
        record = merge_cluster(fragments)
        name_prov = [p for p in record.provenance if p.field == "full_name"]
        assert len(name_prov) == 2  # Both sources tracked
        winners = [p for p in name_prov if p.is_winner]
        # When both sources agree on the same value with equal scores,
        # both may be marked as winners (corroboration). At least 1 winner.
        assert len(winners) >= 1

    def test_deterministic_candidate_id(self) -> None:
        """Same inputs produce same candidate_id across runs."""
        fragments = [
            _make_fragment(SourceType.CSV, {"emails": ["john@test.com"]}),
        ]
        id1 = merge_cluster(fragments).candidate_id
        id2 = merge_cluster(fragments).candidate_id
        assert id1 == id2

    def test_empty_cluster_raises(self) -> None:
        """Empty cluster raises ValueError."""
        with pytest.raises(ValueError):
            merge_cluster([])

    def test_null_field_stays_null(self) -> None:
        """Fields not provided by any source stay None (never invented)."""
        fragments = [
            _make_fragment(SourceType.CSV, {"full_name": "John Smith"}),
        ]
        record = merge_cluster(fragments)
        assert record.years_experience is None
        assert record.headline is None
