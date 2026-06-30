"""Pipeline-wide constants and tunable configuration.

All "magic numbers" live here — source trust priors, confidence thresholds,
field importance weights, and extraction confidence defaults. These are
documented and tunable without code changes to the pipeline logic.

Design principle: no hardcoded numbers scattered in business logic.
If a reviewer asks "where did 0.95 come from?", the answer is always
"constants.py, line N, with this documented rationale."
"""

from src.models.enums import ExtractionMethod, SourceType


# ---------------------------------------------------------------------------
# Source trust priors
# ---------------------------------------------------------------------------
# Static, configurable prior on how reliable each source type is.
# Ordering rationale:
#   structured-curated (CSV) > structured-mapped (ATS) > free-text (notes)
# These can be overridden at runtime via data/source_trust.json.

SOURCE_TRUST: dict[SourceType, float] = {
    SourceType.CSV: 0.95,           # Structured, human-curated, labeled fields
    SourceType.ATS_JSON: 0.90,      # Structured but schema-mismatched (mapping risk)
    SourceType.RECRUITER_NOTES: 0.60,  # Free-text, extraction is fuzzy
}


# ---------------------------------------------------------------------------
# Extraction confidence defaults
# ---------------------------------------------------------------------------
# How confident are we in the extraction method itself?
# These priors are multiplied with source_trust and validation_score.

EXTRACTION_CONFIDENCE: dict[ExtractionMethod, float] = {
    ExtractionMethod.DIRECT_FIELD_READ: 0.95,   # CSV column → direct read
    ExtractionMethod.ATS_MAPPED: 0.90,          # ATS path matched via mapping
    ExtractionMethod.REGEX_EXTRACTED: 0.80,      # Regex hit in free text
    ExtractionMethod.FUZZY_MATCHED: 0.75,        # Fuzzy match (baseline, scaled by score)
    ExtractionMethod.DERIVED: 0.70,              # Computed from other fields
}


# ---------------------------------------------------------------------------
# Validation scores
# ---------------------------------------------------------------------------
# Applied after normalization (validate-then-normalize is atomic).
# A validation_score of 0.0 zeroes the entire merge score — invalid values
# can NEVER win a merge, regardless of source trust.

VALIDATION_PASSED: float = 1.0        # Clean validation pass
VALIDATION_COERCED: float = 0.8       # Passed with type coercion
VALIDATION_FAILED: float = 0.0        # Failed — zeroes the product


# ---------------------------------------------------------------------------
# Entity resolution thresholds
# ---------------------------------------------------------------------------
# Similarity thresholds for entity resolution (0-100 scale to match RapidFuzz)
NAME_SIMILARITY_THRESHOLD: float = 85.0
COMPANY_SIMILARITY_THRESHOLD: float = 80.0


# ---------------------------------------------------------------------------
# Skill normalization
# ---------------------------------------------------------------------------
# Fuzzy match threshold for skill canonicalization.
# Set at 95 (not 90) because short strings have deceptively generous edit
# distances — "Java" vs "JavaScript" scores ~88-91 at WRatio, which at
# threshold 90 would be a dangerous false positive.

SKILL_FUZZY_THRESHOLD: int = 85


# ---------------------------------------------------------------------------
# Merge: corroboration bonus
# ---------------------------------------------------------------------------
# When N sources agree on a value, the winning score is multiplied by:
#   min(1.0, 1 + CORROBORATION_BONUS * (N - 1))
# This rewards consensus without exceeding 1.0.

CORROBORATION_BONUS: float = 0.1


# ---------------------------------------------------------------------------
# Confidence: field importance weights for overall_confidence
# ---------------------------------------------------------------------------
# Identity fields weighted higher because they're the most critical for
# downstream matching and trust. A profile with high-confidence email+name
# but low-confidence headline is still trustworthy.

FIELD_WEIGHTS: dict[str, float] = {
    "full_name": 3.0,
    "emails": 3.0,
    "phones": 2.0,
    "current_company": 2.0,
    "title": 1.5,
    "skills": 2.0,
    "location": 1.0,
    "headline": 1.0,
    "years_experience": 1.0,
    "experience": 1.5,
    "education": 1.0,
    "links": 0.5,
}


# ---------------------------------------------------------------------------
# Phone normalization defaults
# ---------------------------------------------------------------------------
# Default region for phone parsing when no country context is available.
# Documented assumption — stated in README.

DEFAULT_PHONE_REGION: str = "IN"


# ---------------------------------------------------------------------------
# ATS JSON field mapping
# ---------------------------------------------------------------------------
# Maps ATS-specific field names to canonical field names.
# This is the schema-mismatch translation layer — the ATS uses its own
# naming conventions, and this mapping is the single source of truth
# for the translation. Adding a new ATS field = adding one line here.

ATS_FIELD_MAPPING: dict[str, str] = {
    "candidate_name": "full_name",
    "applicant_name": "full_name",
    "contact_email": "emails",
    "email_address": "emails",
    "contact_phone": "phones",
    "phone_number": "phones",
    "current_employer": "current_company",
    "company": "current_company",
    "organization": "current_company",
    "job_title": "title",
    "position": "title",
    "role": "title",
    "city": "location.city",
    "state": "location.region",
    "region": "location.region",
    "country": "location.country",
    "technical_skills": "skills",
    "competencies": "skills",
    "skill_set": "skills",
    "linkedin_url": "links.linkedin",
    "github_url": "links.github",
    "portfolio_url": "links.portfolio",
    "headline": "headline",
    "summary": "headline",
    "professional_summary": "headline",
    "years_of_experience": "years_experience",
    "total_experience": "years_experience",
    "work_history": "experience",
    "employment_history": "experience",
    "education_history": "education",
    "academic_background": "education",
}
