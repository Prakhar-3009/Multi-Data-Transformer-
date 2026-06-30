# Multi-Source Candidate Data Transformer

A production-grade data pipeline that ingests candidate information from three heterogeneous sources (Recruiter CSV, ATS JSON, Recruiter Notes), resolves entity matches, merges conflicting data with provenance tracking, and outputs a unified canonical dataset shaped by a configurable output schema.

## Features

* **Multi-Source Ingestion**: Parses structured (CSV), semi-structured (JSON), and unstructured (Notes) data.
* **Conservative Extraction**: Regex and fuzzy matching extract only high-confidence fields, deliberately abstaining on ambiguous data rather than guessing.
* **Entity Resolution**: Uses O(n) blocking (email, phone) and Union-Find algorithms to identify and merge candidate records across sources.
* **Intelligent Merging**: Resolves conflicts using a "survivorship" scoring model based on source trust and extraction confidence.
* **Config-Driven Output**: Decouples the internal canonical model from external outputs. Use JSON schemas to dynamically shape the final output without changing any core code.
* **Interactive UI**: A built-in Streamlit app provides a rich, tabbed interface to test and compare different JSON output configurations on the fly.

## Quick Start

### 1. Install Dependencies
```bash
pip install -e .
pip install streamlit
```

### 2. Run the Interactive UI (Recommended)
Launch the Streamlit dashboard to explore the pipeline, compare configuration presets, and write custom JSON schemas dynamically.
```bash
streamlit run app.py
```

### 3. Run via CLI
You can also run the pipeline directly from the command line.

**Run with default config:**
```bash
python -m src.cli \
    --csv data/sample_inputs/candidates.csv \
    --json data/sample_inputs/ats_candidates.json \
    --text data/sample_inputs/recruiter_notes.txt \
    --config data/configs/default_config.json \
    --output output.json
```

**Run with custom config (different output shape, no code changes):**
```bash
python -m src.cli \
    --csv data/sample_inputs/candidates.csv \
    --json data/sample_inputs/ats_candidates.json \
    --text data/sample_inputs/recruiter_notes.txt \
    --config data/configs/custom_config.json \
    --output custom_output.json
```

### 4. Run Tests
```bash
python -m pytest tests/ -v
```

## Architecture

```text
┌──────────────┐   ┌──────────────┐   ┌──────────────┐
│  CSV Parser  │   │  JSON Parser │   │  Text Parser  │
└──────┬───────┘   └──────┬───────┘   └──────┬────────┘
       │                  │                   │
       ▼                  ▼                   ▼
┌──────────────┐   ┌──────────────┐   ┌───────────────┐
│CSV Extractor │   │JSON Extractor│   │Text Extractor │
└──────┬───────┘   └──────┬───────┘   └──────┬────────┘
       │                  │                   │
       └──────────────────┴───────────────────┘
                          │
                          ▼  CandidateFragments
                ┌─────────────────┐
                │  Normalization  │
                └────────┬────────┘
                         │
                         ▼  Normalized Fragments
                ┌─────────────────┐
                │ Entity          │
                │ Resolution      │
                └────────┬────────┘
                         │
                         ▼  Clusters
                ┌─────────────────┐
                │ Merge Engine    │
                └────────┬────────┘
                         │
                         ▼  CanonicalRecords
                ┌─────────────────┐
                │ Projection      │
                │ Engine          │
                └────────┬────────┘
                         │
                         ▼  Output JSON
```

## Package Structure

```text
src/
├── core/
│   ├── constants.py      # Business rule constants (thresholds, trust scores)
│   ├── exceptions.py     # Exception hierarchy (data vs config errors)
│   └── pipeline.py       # Pipeline orchestrator
├── models/
│   ├── enums.py           # SourceType, ExtractionMethod
│   ├── fields.py          # FieldValue, ProvenanceEntry
│   ├── fragments.py       # CandidateFragment (per-source)
│   ├── canonical.py       # CanonicalRecord (merged, internal)
│   └── config.py          # OutputConfig, FieldSpec
├── normalizers/
│   ├── phone.py           # E.164 normalization via phonenumbers
│   ├── date.py            # YYYY-MM normalization via dateutil
│   ├── skill.py           # Alias dict + fuzzy matching (threshold=85)
│   ├── email.py           # RFC validation + lowercase
│   ├── country.py         # ISO-3166-α2 via pycountry
│   └── normalizer.py      # NormalizationEngine orchestrator
├── parsers/
│   ├── base.py            # BaseParser ABC
│   ├── csv_parser.py      # Encoding fallback, delimiter sniffing
│   ├── json_parser.py     # Multi-shape JSON handling
│   └── text_parser.py     # Block splitting, whitespace normalization
├── extractors/
│   ├── base.py            # BaseExtractor ABC
│   ├── csv_extractor.py   # Direct column mapping
│   ├── json_extractor.py  # ATS field mapping + nested pattern extraction
│   └── text_extractor.py  # Conservative regex extraction
├── resolution/
│   ├── union_find.py      # DSU with path compression + union by rank
│   ├── blocking.py        # Email + phone blocking (O(n))
│   ├── matcher.py         # Fuzzy name matching gated by company
│   ├── entity_resolver.py # 3-stage resolution pipeline
│   └── merge.py           # Survivorship scoring + provenance
├── projection/
│   ├── path_resolver.py   # 4 path types + MISSING sentinel
│   └── projector.py       # Config-driven output shaping
└── cli.py                 # Minimal argparse entry point
```

## Key Design Decisions

### 1. Honesty over Completeness
"Wrong but confident is worse than honestly empty." If a field cannot be confidently extracted or normalized, it is `null` — never invented. The notes parser is deliberately conservative: it extracts only what clears a confidence bar.

### 2. Validate-then-Normalize (Atomic)
Every normalizer performs validation and normalization as a single atomic operation. A value that fails validation is dropped to `null` — it never enters the pipeline in an invalid state.

### 3. Entity Resolution: Blocking + Union-Find
- **Blocking** (email → phone → fuzzy name) reduces O(n²) pairwise comparisons to O(n).
- **Union-Find** with path compression ensures transitive closure: if A matches B and B matches C, then A, B, C are all the same person.
- **Conservative matching**: the fuzzy matcher gates name similarity by company similarity to prevent false merges of common names.

### 4. Merge Scoring: Trust × Confidence
Merge score = `source_trust × extraction_confidence`. The multiplicative formula ensures any zero factor kills the value. Corroboration bonus applies when N sources agree on the same value.

### 5. MISSING ≠ None (Projection)
The path resolver distinguishes between:
- `None`: "the field exists but has no value" → output as `null`
- `MISSING`: "the path doesn't resolve at all" → apply `on_missing` strategy (null/omit/error)

This is the single most important correctness detail in the projection engine.

### 6. Config-Driven Output (The "Twist")
The projection engine decouples the internal canonical model from the external output schema. Same engine + different config → different output shape, zero code changes. The config supports:
- **Field renaming**: `"path": "candidate_name", "from": "full_name"`
- **Array indexing**: `"from": "emails[0]"`
- **Array projection**: `"from": "skills[].name"`
- **Nested access**: `"from": "location.city"`
- **Missing strategies**: `"on_missing": "null"` / `"omit"` / `"error"`
- **Metadata toggles**: `include_confidence`, `include_provenance`

## Streamlit App Features (`app.py`)
The included Streamlit dashboard provides a powerful way to visualize the pipeline in action:
- **Pipeline Metrics**: See exactly how many fragments were ingested and how they resolved into canonical candidates.
- **Config Presets**: Quickly toggle between different JSON output shapes (Default, HR CRM, Tech Screening, Compliance Audit).
- **Custom Config Editor**: Write your own JSON projection schemas in real-time in the sidebar and instantly see the output format change.
- **Candidate Comparison Tabs**: View side-by-side tabs to inspect what a candidate's output looks like under every available configuration simultaneously.

## Provenance

Every field value carries full provenance metadata. You can always explain WHY a value was chosen and what alternatives were available.
```json
{
  "field": "full_name",
  "source": "csv",
  "method": "direct_field_read",
  "value": "John Smith",
  "confidence": 0.9025,
  "is_winner": true
}
```

## Dependencies

- `pydantic` — Pydantic v2 for model validation
- `phonenumbers` — E.164 phone normalization
- `python-dateutil` — Date parsing
- `rapidfuzz` — Fuzzy string matching (skills, names)
- `pycountry` — ISO-3166 country code lookup
- `streamlit` — Interactive frontend dashboard
- `pytest` — Testing

## Test Coverage

```text
120 tests, 0.83s
├── test_normalizers.py   — 39 tests
├── test_parsers.py       — 13 tests
├── test_extractors.py    — 12 tests
├── test_resolution.py    — 15 tests
├── test_projection.py    — 12 tests
└── test_pipeline.py      —  9 tests
```
