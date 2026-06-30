"""Merge engine — survivorship + conflict resolution.

The algorithmic heart of the pipeline. Given a cluster of fragments
(same person from multiple sources), produces one canonical record by:

1. For scalar fields: pick the winner by score = trust × confidence
   (multiplicative — any zero factor kills the value).
2. For array fields: union, deduplicate, sort (retain all valid values).
3. For all fields: record full provenance (winners and losers).
4. Corroboration bonus: when N sources agree, multiply score by
   min(1.0, 1 + 0.1*(N-1)).
5. Tie-breaking: higher source trust → lexical order (deterministic).

The merge NEVER invents values. If all sources provide null for a field,
the canonical record has null for that field.
"""

from __future__ import annotations

import hashlib
import logging
from collections import defaultdict

from src.core.constants import (
    CORROBORATION_BONUS,
    FIELD_WEIGHTS,
    SOURCE_TRUST,
)
from src.models.canonical import (
    CanonicalRecord,
    EducationEntry,
    ExperienceEntry,
    Links,
    Location,
    SkillEntry,
)
from src.models.enums import ExtractionMethod, SourceType
from src.models.fields import FieldValue, ProvenanceEntry
from src.models.fragments import CandidateFragment

logger = logging.getLogger(__name__)

# Scalar fields that trigger winner-selection (only one value kept)
_SCALAR_FIELDS = {
    "full_name", "current_company", "title", "headline",
    "years_experience",
    # NOTE: location is NOT here — it has special merge logic
    # that handles both dict and string forms
}

# Array fields that get unioned (all valid values kept)
_ARRAY_FIELDS = {"emails", "phones", "skills"}


def merge_cluster(
    fragments: list[CandidateFragment],
) -> CanonicalRecord:
    """Merge a cluster of fragments into one canonical record.

    Args:
        fragments: List of CandidateFragments believed to be the same person.
                   Must have at least one fragment.

    Returns:
        A single CanonicalRecord with merged fields, full provenance,
        and computed confidence scores.
    """
    if not fragments:
        raise ValueError("Cannot merge empty cluster")

    all_provenance: list[ProvenanceEntry] = []
    field_confidences: dict[str, float] = {}

    # Collect all field values across fragments, grouped by field name
    field_candidates: dict[str, list[tuple[FieldValue, float]]] = defaultdict(list)
    for fragment in fragments:
        trust = fragment.source_trust
        for field_name, fv in fragment.fields.items():
            if fv.value is not None:
                field_candidates[field_name].append((fv, trust))

    # --- Merge scalar fields (pick winner) ---
    merged_scalars: dict[str, object] = {}
    for field_name in _SCALAR_FIELDS:
        candidates = field_candidates.get(field_name, [])
        if not candidates:
            continue

        winner_value, winner_confidence, provenance_entries = _pick_winner(
            field_name, candidates
        )
        if winner_value is not None:
            merged_scalars[field_name] = winner_value
            field_confidences[field_name] = winner_confidence
        all_provenance.extend(provenance_entries)

    # --- Merge array fields (union) ---
    merged_emails = _merge_email_arrays(field_candidates.get("emails", []))
    merged_phones = _merge_phone_arrays(field_candidates.get("phones", []))
    merged_skills, skill_provenance = _merge_skills(
        field_candidates.get("skills", [])
    )
    all_provenance.extend(skill_provenance)

    if merged_emails:
        field_confidences["emails"] = max(
            fv.confidence * trust
            for fv, trust in field_candidates.get("emails", [])
        )
    if merged_phones:
        field_confidences["phones"] = max(
            fv.confidence * trust
            for fv, trust in field_candidates.get("phones", [])
        )
    if merged_skills:
        field_confidences["skills"] = max(s.confidence for s in merged_skills)

    # --- Build location (special merge: handles dicts, strings, dotted sub-fields) ---
    location = _merge_location(field_candidates)
    if location:
        field_confidences["location"] = max(
            (fv.confidence * trust)
            for fv, trust in field_candidates.get("location", [(FieldValue(value=None, source=SourceType.CSV, method=ExtractionMethod.DIRECT_FIELD_READ, confidence=0.5), 0.5)])
            if fv.value is not None
        ) if field_candidates.get("location") else 0.5

    # --- Build links ---
    links = _merge_links(field_candidates)

    # --- Build experience & education ---
    experience = _merge_experience(field_candidates.get("experience", []))
    education = _merge_education(field_candidates.get("education", []))

    # --- Derive years_experience if possible ---
    years_exp = merged_scalars.get("years_experience")
    if years_exp is not None:
        try:
            years_exp = float(years_exp)
        except (ValueError, TypeError):
            years_exp = None

    # --- Generate candidate_id (deterministic hash) ---
    candidate_id = _generate_candidate_id(
        merged_emails, merged_phones, merged_scalars.get("full_name")
    )

    # --- Compute overall confidence ---
    overall_confidence = _compute_overall_confidence(field_confidences)

    return CanonicalRecord(
        candidate_id=candidate_id,
        full_name=merged_scalars.get("full_name"),
        emails=merged_emails,
        phones=merged_phones,
        current_company=merged_scalars.get("current_company"),
        title=merged_scalars.get("title"),
        location=location,
        links=links,
        headline=merged_scalars.get("headline"),
        years_experience=years_exp,
        skills=merged_skills,
        experience=experience,
        education=education,
        provenance=all_provenance,
        overall_confidence=overall_confidence,
    )




def _pick_winner(
    field_name: str,
    candidates: list[tuple[FieldValue, float]],
) -> tuple[object, float, list[ProvenanceEntry]]:
    """Pick the winning value for a scalar field using merge scoring.

    Score = source_trust × extraction_confidence (× validation, already
    factored into FieldValue.confidence).

    Returns:
        Tuple of (winning_value, winning_score, provenance_entries).
    """
    scored: list[tuple[object, float, FieldValue, float]] = []

    for fv, trust in candidates:
        if fv.value is None:
            continue
        # Merge score = trust × confidence (validation already embedded)
        score = trust * fv.confidence
        scored.append((fv.value, score, fv, trust))

    if not scored:
        return None, 0.0, []

    # Check for corroboration bonus: count how many sources agree on the value
    value_counts: dict[str, int] = defaultdict(int)
    for value, _, _, _ in scored:
        val_key = str(value).strip().lower() if isinstance(value, str) else str(value)
        value_counts[val_key] += 1

    # Apply corroboration bonus to scores
    boosted_scored: list[tuple[object, float, FieldValue, float]] = []
    for value, score, fv, trust in scored:
        val_key = str(value).strip().lower() if isinstance(value, str) else str(value)
        n_agree = value_counts[val_key]
        if n_agree > 1:
            bonus = min(1.0, 1.0 + CORROBORATION_BONUS * (n_agree - 1))
            score = min(1.0, score * bonus)
        boosted_scored.append((value, score, fv, trust))

    # Sort by score (desc), then trust (desc), then lexical (deterministic)
    boosted_scored.sort(
        key=lambda x: (-x[1], -x[3], str(x[0]).lower())
    )

    winner_value = boosted_scored[0][0]
    winner_score = boosted_scored[0][1]

    # Build provenance entries for ALL candidates (winners and losers)
    provenance: list[ProvenanceEntry] = []
    for value, score, fv, trust in boosted_scored:
        provenance.append(ProvenanceEntry(
            field=field_name,
            source=fv.source,
            method=fv.method,
            value=value,
            confidence=score,
            is_winner=(value == winner_value and score == winner_score),
        ))

    return winner_value, winner_score, provenance


def _merge_email_arrays(
    candidates: list[tuple[FieldValue, float]],
) -> list[str]:
    """Merge email arrays: union, deduplicate, sort."""
    all_emails: set[str] = set()
    for fv, _ in candidates:
        val = fv.value
        if isinstance(val, str):
            if val.strip():
                all_emails.add(val.strip().lower())
        elif isinstance(val, list):
            for e in val:
                if isinstance(e, str) and e.strip():
                    all_emails.add(e.strip().lower())
    return sorted(all_emails)


def _merge_phone_arrays(
    candidates: list[tuple[FieldValue, float]],
) -> list[str]:
    """Merge phone arrays: union, deduplicate, sort."""
    all_phones: set[str] = set()
    for fv, _ in candidates:
        val = fv.value
        if isinstance(val, str):
            if val.strip():
                all_phones.add(val.strip())
        elif isinstance(val, list):
            for p in val:
                if isinstance(p, str) and p.strip():
                    all_phones.add(p.strip())
    return sorted(all_phones)


def _merge_skills(
    candidates: list[tuple[FieldValue, float]],
) -> tuple[list[SkillEntry], list[ProvenanceEntry]]:
    """Merge skills: union by canonical name, track per-skill confidence."""
    skill_map: dict[str, dict] = {}  # canonical_name → {confidence, sources}
    provenance: list[ProvenanceEntry] = []

    for fv, trust in candidates:
        val = fv.value
        if not isinstance(val, list):
            continue

        for item in val:
            if isinstance(item, dict):
                name = item.get("name", "")
                conf = item.get("confidence", fv.confidence)
            elif isinstance(item, str):
                name = item.strip()
                conf = fv.confidence
            else:
                continue

            if not name:
                continue

            canonical_name = name.strip()
            score = trust * conf

            if canonical_name not in skill_map:
                skill_map[canonical_name] = {
                    "confidence": score,
                    "sources": [fv.source],
                }
            else:
                existing = skill_map[canonical_name]
                # Take max confidence (corroboration — confirmed by multiple sources)
                existing["confidence"] = max(existing["confidence"], score)
                if fv.source not in existing["sources"]:
                    existing["sources"].append(fv.source)

            provenance.append(ProvenanceEntry(
                field=f"skills.{canonical_name}",
                source=fv.source,
                method=fv.method,
                value=canonical_name,
                confidence=score,
                is_winner=True,  # All skills are "winners" (union, not pick-one)
            ))

    skills = [
        SkillEntry(
            name=name,
            confidence=min(1.0, data["confidence"]),
            sources=sorted(data["sources"], key=lambda s: s.value),
        )
        for name, data in sorted(skill_map.items())
    ]

    return skills, provenance


def _merge_location(
    field_candidates: dict[str, list[tuple[FieldValue, float]]],
) -> Location | None:
    """Merge location from location field values and dotted sub-fields.

    Handles multiple location value types:
    - dict: {"city": "X", "region": "Y", "country": "Z"}
    - str: "City, Country" (simple text)
    - dotted sub-fields: location.city, location.region, location.country
    """
    city = None
    region = None
    country = None

    # Try location field candidates (may be dict or string)
    location_candidates = field_candidates.get("location", [])
    if location_candidates:
        # Pick the highest-confidence location
        best_fv, best_trust = max(
            location_candidates, key=lambda c: c[1] * c[0].confidence
        )
        val = best_fv.value

        if isinstance(val, dict):
            city = val.get("city")
            region = val.get("region")
            country = val.get("country")
        elif isinstance(val, str):
            # Try to parse "City, Country" or "City, State, Country"
            parts = [p.strip() for p in val.split(",")]
            if len(parts) >= 1:
                city = parts[0] or None
            if len(parts) >= 2:
                country = parts[-1] or None
            if len(parts) >= 3:
                region = parts[1] or None

    # Try dotted sub-fields (override only if not already set)
    for field_name, canonical_key in [
        ("location.city", "city"),
        ("location.region", "region"),
        ("location.country", "country"),
    ]:
        candidates = field_candidates.get(field_name, [])
        if not candidates:
            continue

        current = {"city": city, "region": region, "country": country}
        if current[canonical_key] is not None:
            continue  # Already set from the main location field

        best = max(candidates, key=lambda c: c[1] * c[0].confidence)
        val = best[0].value
        if isinstance(val, str) and val.strip():
            if canonical_key == "city":
                city = val.strip()
            elif canonical_key == "region":
                region = val.strip()
            elif canonical_key == "country":
                country = val.strip()

    if city or region or country:
        return Location(city=city, region=region, country=country)
    return None


def _merge_links(
    field_candidates: dict[str, list[tuple[FieldValue, float]]],
) -> Links | None:
    """Merge links from various link fields."""
    linkedin = None
    github = None
    portfolio = None
    other: list[str] = []

    for field_name, attr in [
        ("links.linkedin", "linkedin"),
        ("links.github", "github"),
        ("links.portfolio", "portfolio"),
    ]:
        candidates = field_candidates.get(field_name, [])
        if candidates:
            best = max(candidates, key=lambda c: c[1] * c[0].confidence)
            val = best[0].value
            if isinstance(val, str) and val.strip():
                if attr == "linkedin":
                    linkedin = val.strip()
                elif attr == "github":
                    github = val.strip()
                elif attr == "portfolio":
                    portfolio = val.strip()

    if linkedin or github or portfolio or other:
        return Links(
            linkedin=linkedin, github=github,
            portfolio=portfolio, other=other,
        )
    return None


def _merge_experience(
    candidates: list[tuple[FieldValue, float]],
) -> list[ExperienceEntry]:
    """Merge experience entries from multiple sources."""
    all_exp: list[ExperienceEntry] = []
    seen: set[str] = set()

    for fv, _ in candidates:
        val = fv.value
        if not isinstance(val, list):
            continue
        for item in val:
            if not isinstance(item, dict):
                continue
            # Dedup by company+title+start
            key = f"{item.get('company', '')}|{item.get('title', '')}|{item.get('start', '')}".lower()
            if key in seen:
                continue
            seen.add(key)
            all_exp.append(ExperienceEntry(
                company=item.get("company"),
                title=item.get("title"),
                start=item.get("start"),
                end=item.get("end"),
                summary=item.get("summary"),
            ))

    # Sort by start date descending (most recent first), deterministic
    all_exp.sort(key=lambda e: (e.start or "", e.company or ""), reverse=True)
    return all_exp


def _merge_education(
    candidates: list[tuple[FieldValue, float]],
) -> list[EducationEntry]:
    """Merge education entries from multiple sources."""
    all_edu: list[EducationEntry] = []
    seen: set[str] = set()

    for fv, _ in candidates:
        val = fv.value
        if not isinstance(val, list):
            continue
        for item in val:
            if not isinstance(item, dict):
                continue
            key = f"{item.get('institution', '')}|{item.get('degree', '')}".lower()
            if key in seen:
                continue
            seen.add(key)

            end_year = item.get("end_year")
            if end_year is not None:
                try:
                    end_year = int(end_year)
                except (ValueError, TypeError):
                    end_year = None

            all_edu.append(EducationEntry(
                institution=item.get("institution"),
                degree=item.get("degree"),
                field_of_study=item.get("field") or item.get("field_of_study"),
                end_year=end_year,
            ))

    all_edu.sort(key=lambda e: (e.end_year or 0, e.institution or ""), reverse=True)
    return all_edu


def _generate_candidate_id(
    emails: list[str],
    phones: list[str],
    name: object,
) -> str:
    """Generate a deterministic candidate ID from the strongest match key.

    Priority: email[0] (most unique) → phone[0] → name → fallback.
    Hash ensures stable, fixed-length IDs across runs.
    """
    if emails:
        seed = f"email:{emails[0]}"
    elif phones:
        seed = f"phone:{phones[0]}"
    elif name:
        seed = f"name:{str(name).lower().strip()}"
    else:
        seed = "unknown"

    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]


def _compute_overall_confidence(
    field_confidences: dict[str, float],
) -> float:
    """Compute overall confidence as weighted mean of field confidences.

    Identity fields (email, name) weighted higher than optional fields.
    """
    if not field_confidences:
        return 0.0

    weighted_sum = 0.0
    weight_total = 0.0

    for field_name, confidence in field_confidences.items():
        weight = FIELD_WEIGHTS.get(field_name, 1.0)
        weighted_sum += confidence * weight
        weight_total += weight

    if weight_total == 0:
        return 0.0

    return min(1.0, weighted_sum / weight_total)
