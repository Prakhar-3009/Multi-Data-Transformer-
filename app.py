"""Streamlit UI for the Multi-Source Candidate Data Transformer.

Run with: streamlit run app.py
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import streamlit as st

from src.core.pipeline import Pipeline
from src.models.config import OutputConfig

# --- Page config ---
st.set_page_config(
    page_title="Candidate Data Transformer",
    page_icon="🔀",
    layout="wide",
    initial_sidebar_state="expanded",
)

# --- Custom CSS for premium look ---
st.markdown("""
<style>
    .main > div { padding-top: 1rem; }
    .stMetric { 
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 1rem;
        border-radius: 0.75rem;
        color: white;
    }
    .stMetric label { color: rgba(255,255,255,0.8) !important; }
    .stMetric [data-testid="stMetricValue"] { color: white !important; font-size: 2rem !important; }
    div[data-testid="stExpander"] {
        border: 1px solid #e0e0e0;
        border-radius: 0.5rem;
        margin-bottom: 0.5rem;
    }
    .source-badge {
        display: inline-block;
        padding: 0.15rem 0.5rem;
        border-radius: 1rem;
        font-size: 0.75rem;
        font-weight: 600;
        margin: 0.1rem;
    }
    .source-csv { background: #dbeafe; color: #1e40af; }
    .source-ats_json { background: #dcfce7; color: #166534; }
    .source-recruiter_notes { background: #fef3c7; color: #92400e; }
    .skill-chip {
        display: inline-block;
        padding: 0.2rem 0.6rem;
        border-radius: 1rem;
        font-size: 0.8rem;
        margin: 0.15rem;
        background: #f1f5f9;
        border: 1px solid #cbd5e1;
    }
    .confidence-high { color: #16a34a; font-weight: 700; }
    .confidence-medium { color: #d97706; font-weight: 700; }
    .confidence-low { color: #dc2626; font-weight: 700; }
</style>
""", unsafe_allow_html=True)


def get_confidence_class(conf: float) -> str:
    if conf >= 0.85:
        return "confidence-high"
    elif conf >= 0.60:
        return "confidence-medium"
    return "confidence-low"


def render_source_badges(sources: set[str]) -> str:
    badges = []
    for s in sorted(sources):
        css_class = f"source-{s}"
        label = {"csv": "CSV", "ats_json": "ATS JSON", "recruiter_notes": "Notes"}.get(s, s)
        badges.append(f'<span class="source-badge {css_class}">{label}</span>')
    return " ".join(badges)


def render_skill_chips(skills: list) -> str:
    chips = []
    for s in skills:
        name = s["name"] if isinstance(s, dict) else s
        chips.append(f'<span class="skill-chip">{name}</span>')
    return " ".join(chips)


# --- Sidebar ---
st.sidebar.title("🔀 Data Sources")
st.sidebar.markdown("Upload your candidate data files, or use the built-in sample data.")

use_samples = st.sidebar.checkbox("Use sample data", value=True, help="Load the built-in sample files")

csv_file = None
json_file = None
text_file = None

if not use_samples:
    csv_file = st.sidebar.file_uploader("📄 Recruiter CSV", type=["csv"])
    json_file = st.sidebar.file_uploader("📋 ATS JSON", type=["json"])
    text_file = st.sidebar.file_uploader("📝 Recruiter Notes", type=["txt"])

st.sidebar.markdown("---")
st.sidebar.title("⚙️ Output Config")

CONFIG_PRESETS = {
    "📋 Default (Full + Provenance)": {
        "file": "data/configs/default_config.json",
        "desc": "11 fields + confidence + full provenance audit trail",
    },
    "👥 HR CRM (Contact Only)": {
        "file": "data/configs/hr_crm_config.json",
        "desc": "4 fields: name, email, phone, company. No metadata.",
    },
    "💻 Tech Screening (Skills Focus)": {
        "file": "data/configs/tech_screening_config.json",
        "desc": "6 fields: candidate, skills, GitHub, years, role + confidence",
    },
    "🔍 Compliance Audit (Data Lineage)": {
        "file": "data/configs/compliance_audit_config.json",
        "desc": "4 fields but FULL provenance + confidence for audit trail",
    },
    "🔄 Custom Minimal (Renamed Keys)": {
        "file": "data/configs/custom_config.json",
        "desc": "4 renamed fields: candidate_name, contact_email, skill_list, company",
    },
    "✏️ Write Your Own": {
        "file": None,
        "desc": "Paste or edit your own JSON config below",
    },
}

config_choice = st.sidebar.radio(
    "Output Schema",
    list(CONFIG_PRESETS.keys()),
    help="Each preset produces a different JSON output shape from the same data — zero code changes"
)

st.sidebar.caption(CONFIG_PRESETS[config_choice]["desc"])

# Custom config text area
custom_config_json = None
if config_choice == "✏️ Write Your Own":
    default_custom = json.dumps({
        "fields": [
            {"path": "name", "from": "full_name", "type": "string", "required": True},
            {"path": "email", "from": "emails[0]", "type": "string"},
            {"path": "skills", "from": "skills[].name", "type": "string[]"},
            {"path": "city", "from": "location.city", "type": "string", "on_missing": "omit"},
        ],
        "include_confidence": True,
        "include_provenance": False,
        "on_missing": "null",
    }, indent=2)
    custom_config_json = st.sidebar.text_area(
        "Custom Config JSON",
        value=default_custom,
        height=300,
        help="Edit this JSON to control the output shape. Supports: field renaming, path expressions (emails[0], skills[].name, location.city), on_missing strategies (null/omit/error)."
    )

# --- Main area ---
st.title("🔀 Multi-Source Candidate Data Transformer")
st.markdown(
    "Ingests candidate data from **3 heterogeneous sources**, resolves entity matches, "
    "merges with provenance tracking, and outputs a **configurable canonical dataset**."
)

run_button = st.button("🚀 Run Pipeline", type="primary", use_container_width=True)

if run_button:
    with st.spinner("Processing..."):
        pipeline = Pipeline()

        # Resolve file paths
        if use_samples:
            csv_path = Path("data/sample_inputs/candidates.csv")
            json_path = Path("data/sample_inputs/ats_candidates.json")
            text_path = Path("data/sample_inputs/recruiter_notes.txt")
        else:
            csv_path = None
            json_path = None
            text_path = None

            if csv_file is not None:
                tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".csv")
                tmp.write(csv_file.read())
                tmp.flush()
                csv_path = Path(tmp.name)

            if json_file is not None:
                tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
                tmp.write(json_file.read())
                tmp.flush()
                json_path = Path(tmp.name)

            if text_file is not None:
                tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".txt")
                tmp.write(text_file.read())
                tmp.flush()
                text_path = Path(tmp.name)

        if csv_path is None and json_path is None and text_path is None:
            st.error("Please upload at least one data source or enable sample data.")
            st.stop()

        # Load config
        if config_choice == "✏️ Write Your Own":
            try:
                config_raw = json.loads(custom_config_json)
            except json.JSONDecodeError as e:
                st.error(f"❌ Invalid JSON in custom config: {e}")
                st.stop()
        else:
            config_path = Path(CONFIG_PRESETS[config_choice]["file"])
            config_raw = json.loads(config_path.read_text(encoding="utf-8"))

        try:
            config = OutputConfig.model_validate(config_raw)
        except Exception as e:
            st.error(f"❌ Invalid config schema: {e}")
            st.stop()

        # Run pipeline — raw for metrics
        canonical_records = pipeline.run_raw(
            csv_path=csv_path,
            json_path=json_path,
            text_path=text_path,
        )

        # Run pipeline — projected for output
        results = pipeline.run(
            csv_path=csv_path,
            json_path=json_path,
            text_path=text_path,
            config=config,
        )

    # --- Metrics row ---
    st.markdown("---")
    st.subheader("📊 Pipeline Metrics")

    sources_active = sum([
        csv_path is not None,
        json_path is not None,
        text_path is not None,
    ])

    # Count total fragments
    total_fragments = 0
    if csv_path:
        from src.parsers.csv_parser import RecruiterCSVParser
        from src.extractors.csv_extractor import CSVExtractor
        csv_records = RecruiterCSVParser().parse(csv_path)
        csv_fragments = CSVExtractor().extract(csv_records)
        total_fragments += len(csv_fragments)
    if json_path:
        from src.parsers.json_parser import ATSJSONParser
        from src.extractors.json_extractor import ATSJSONExtractor
        json_records = ATSJSONParser().parse(json_path)
        json_fragments = ATSJSONExtractor().extract(json_records)
        total_fragments += len(json_fragments)
    if text_path:
        from src.parsers.text_parser import RecruiterNotesParser
        from src.extractors.text_extractor import TextExtractor
        text_records = RecruiterNotesParser().parse(text_path)
        text_fragments = TextExtractor().extract(text_records)
        total_fragments += len(text_fragments)

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Sources", f"{sources_active}")
    col2.metric("Raw Fragments", f"{total_fragments}")
    col3.metric("Canonical Candidates", f"{len(canonical_records)}")
    reduction = ((total_fragments - len(canonical_records)) / total_fragments * 100) if total_fragments > 0 else 0
    col4.metric("Dedup Reduction", f"{reduction:.0f}%")

    # --- Source breakdown ---
    st.markdown("---")

    # Count per-source
    source_counts = {}
    for r in canonical_records:
        sources = set()
        for p in r.provenance:
            sources.add(p.source.value)
        for s in sources:
            source_counts[s] = source_counts.get(s, 0) + 1

    multi_source = sum(1 for r in canonical_records if len(set(p.source.value for p in r.provenance)) > 1)

    col_a, col_b = st.columns(2)
    with col_a:
        st.subheader("📈 Source Coverage")
        for src_name, count in sorted(source_counts.items()):
            label = {"csv": "📄 CSV", "ats_json": "📋 ATS JSON", "recruiter_notes": "📝 Notes"}.get(src_name, src_name)
            st.write(f"{label}: **{count}** candidates")
        st.write(f"🔗 **Multi-source merged**: {multi_source} candidates")

    with col_b:
        st.subheader("🎯 Confidence Distribution")
        high = sum(1 for r in canonical_records if r.overall_confidence >= 0.85)
        medium = sum(1 for r in canonical_records if 0.60 <= r.overall_confidence < 0.85)
        low = sum(1 for r in canonical_records if r.overall_confidence < 0.60)
        st.write(f"🟢 High (≥0.85): **{high}**")
        st.write(f"🟡 Medium (0.60-0.85): **{medium}**")
        st.write(f"🔴 Low (<0.60): **{low}**")

    # --- Candidate cards ---
    st.markdown("---")
    st.subheader(f"👤 Candidates ({len(canonical_records)})")

    # Show a banner explaining what the current config does
    field_count = len(config_raw.get("fields", []))
    has_prov = config_raw.get("include_provenance", False)
    has_conf = config_raw.get("include_confidence", False)
    meta_parts = []
    if has_conf:
        meta_parts.append("confidence")
    if has_prov:
        meta_parts.append("provenance")
    meta_str = " + ".join(meta_parts) if meta_parts else "no metadata"

    field_names = [f.get("path", "?") for f in config_raw.get("fields", [])]
    st.info(
        f"**Active Config: {config_choice}**\n\n"
        f"**{field_count} fields:** `{'`, `'.join(field_names)}` · {meta_str}\n\n"
        f"*Switch configs in the sidebar to see how the JSON output changes — zero code changes required.*"
    )

    for i, canonical in enumerate(canonical_records):
        candidate_name = canonical.full_name or f"Candidate {i+1}"
        email = canonical.emails[0] if canonical.emails else "N/A"

        # Get provenance sources
        prov_entries = canonical.provenance or []
        sources = set(p.source.value for p in prov_entries)
        conf = canonical.overall_confidence or 0

        with st.expander(f"**{candidate_name}** — {email}", expanded=(i < 3)):
            # Two tabs: Candidate Info and Projected Output
            tab_info, tab_json = st.tabs(["📇 Candidate Info", "📤 Projected JSON Output"])

            with tab_info:
                col1, col2, col3 = st.columns([2, 2, 1])

                with col1:
                    company = canonical.current_company or "—"
                    title = canonical.title or "—"
                    st.markdown(f"**🏢 Company:** {company}")
                    st.markdown(f"**💼 Title:** {title}")

                    loc = canonical.location
                    if loc:
                        city = loc.city or "—"
                        country = loc.country or "—"
                        st.markdown(f"**📍 Location:** {city}, {country}")
                    else:
                        st.markdown("**📍 Location:** —")

                    yoe = canonical.years_experience
                    st.markdown(f"**⏱️ Experience:** {yoe} years" if yoe else "**⏱️ Experience:** —")

                with col2:
                    skills = canonical.skills or []
                    if skills:
                        st.markdown("**🛠️ Skills:**")
                        skill_chips = []
                        for s in skills:
                            skill_chips.append(f'<span class="skill-chip">{s.name}</span>')
                        st.markdown(" ".join(skill_chips), unsafe_allow_html=True)
                    else:
                        st.markdown("**🛠️ Skills:** —")

                    if len(canonical.emails) > 1:
                        st.markdown(f"**📧 All Emails:** {', '.join(canonical.emails)}")

                    phone = canonical.phones[0] if canonical.phones else "—"
                    st.markdown(f"**📱 Phone:** {phone}")

                with col3:
                    if conf:
                        conf_class = get_confidence_class(conf)
                        st.markdown(f'**Confidence:**<br><span class="{conf_class}">{conf:.1%}</span>', unsafe_allow_html=True)

                    if sources:
                        st.markdown(f"**Sources:**<br>{render_source_badges(sources)}", unsafe_allow_html=True)

                # Provenance detail
                if prov_entries:
                    with st.popover("📋 View Provenance"):
                        prov_dicts = [
                            {
                                "field": p.field,
                                "source": p.source.value,
                                "method": p.method.value if hasattr(p.method, 'value') else str(p.method),
                                "value": str(p.value),
                                "confidence": p.confidence,
                                "is_winner": p.is_winner,
                            }
                            for p in prov_entries
                        ]
                        st.json(prov_dicts)

            with tab_json:
                # Show the PROJECTED output for this candidate under the selected config
                if i < len(results):
                    projected = results[i]
                    st.caption(f"Schema: **{config_choice}** — This is the actual JSON output for this candidate.")
                    st.json(projected)

                    # Show what fields are present vs absent
                    fields_present = list(projected.keys())
                    st.markdown(f"**Fields in output ({len(fields_present)}):** `{'`, `'.join(fields_present)}`")

    # --- Multi-config comparison ---
    st.markdown("---")
    st.subheader("🔀 Config Comparison — The Twist")
    st.markdown(
        "**Same candidate, same engine, 5 different configs → 5 different JSON outputs.** "
        "This is the core differentiator: the output schema is driven entirely by a JSON config file. "
        "Zero code changes required."
    )

    first_candidate = canonical_records[0] if canonical_records else None
    if first_candidate:
        from src.projection.projector import project

        st.markdown(f"**Candidate:** {first_candidate.full_name or 'N/A'}")

        # Build tabs for each preset (skip "Write Your Own")
        preset_names = [k for k in CONFIG_PRESETS if CONFIG_PRESETS[k]["file"] is not None]
        tabs = st.tabs(preset_names)

        for tab, preset_name in zip(tabs, preset_names):
            with tab:
                preset_path = Path(CONFIG_PRESETS[preset_name]["file"])
                preset_raw = json.loads(preset_path.read_text(encoding="utf-8"))
                preset_conf = OutputConfig.model_validate(preset_raw)
                preset_output = project(first_candidate, preset_conf)

                col_json, col_cfg = st.columns([3, 2])

                with col_json:
                    st.markdown(f"**Output JSON** — {len(preset_output)} fields")
                    st.json(preset_output)

                with col_cfg:
                    st.markdown("**Config File**")
                    st.code(preset_path.read_text(encoding="utf-8"), language="json")

    # --- Download ---
    st.markdown("---")
    st.subheader("⬇️ Download Output")

    output_json = json.dumps(results, indent=2, default=str)
    st.download_button(
        label=f"⬇️ Download JSON ({config_choice})",
        data=output_json,
        file_name="canonical_candidates.json",
        mime="application/json",
        use_container_width=True,
    )

    with st.expander("View Raw JSON", expanded=False):
        st.code(output_json, language="json")

else:
    # Landing state
    st.info(
        "👈 **Upload your data files** in the sidebar (or use the built-in samples), "
        "then click **Run Pipeline** to see the magic happen."
    )

    st.markdown("### How It Works")
    col1, col2, col3 = st.columns(3)

    with col1:
        st.markdown("#### 1️⃣ Ingest")
        st.markdown(
            "Upload **CSV**, **ATS JSON**, and **Recruiter Notes**. "
            "Each source has its own parser and extractor."
        )

    with col2:
        st.markdown("#### 2️⃣ Resolve & Merge")
        st.markdown(
            "Entity resolution uses **email/phone blocking** + **Union-Find** "
            "to cluster fragments. Merge engine picks winners by trust × confidence."
        )

    with col3:
        st.markdown("#### 3️⃣ Project")
        st.markdown(
            "The projection engine reshapes output via **JSON config**. "
            "Same data, different config → different output shape. Zero code changes."
        )

    st.markdown("### Architecture")
    st.code("""
    CSV ─→ Parser ─→ Extractor ─┐
    JSON ─→ Parser ─→ Extractor ──┼─→ Normalizer ─→ Entity Resolver ─→ Merge ─→ Projector ─→ Output
    Text ─→ Parser ─→ Extractor ─┘
    """, language="text")
