"""Pipeline orchestrator — wires all stages together.

This is the single entry point that runs the full pipeline:
1. Parse sources → raw records
2. Extract → CandidateFragments with provenance
3. Normalize → comparable fragments
4. Entity Resolution → clusters
5. Merge → CanonicalRecords
6. Project → output-shaped dicts
7. Emit → JSON
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from src.core.exceptions import ConfigLoadError, ParseError, SourceError
from src.extractors.csv_extractor import CSVExtractor
from src.extractors.json_extractor import ATSJSONExtractor
from src.extractors.text_extractor import TextExtractor
from src.models.canonical import CanonicalRecord
from src.models.config import OutputConfig
from src.models.fragments import CandidateFragment
from src.normalizers.normalizer import NormalizationEngine
from src.parsers.csv_parser import RecruiterCSVParser
from src.parsers.json_parser import ATSJSONParser
from src.parsers.text_parser import RecruiterNotesParser
from src.projection.projector import project_many
from src.resolution.entity_resolver import resolve_entities
from src.resolution.merge import merge_cluster

logger = logging.getLogger(__name__)


class Pipeline:
    """Full candidate data transformation pipeline.

    Usage:
        pipeline = Pipeline()
        results = pipeline.run(
            csv_path=Path("data/candidates.csv"),
            json_path=Path("data/ats.json"),
            text_path=Path("data/notes.txt"),
            config_path=Path("data/configs/default.json"),
        )
    """

    def __init__(
        self,
        skill_dictionary_path: Path | None = None,
        default_phone_region: str = "IN",
    ) -> None:
        """Initialize the pipeline with configuration.

        Args:
            skill_dictionary_path: Path to skill aliases JSON.
            default_phone_region: Default region for phone parsing.
        """
        # Parsers
        self._csv_parser = RecruiterCSVParser()
        self._json_parser = ATSJSONParser()
        self._text_parser = RecruiterNotesParser()

        # Extractors
        self._csv_extractor = CSVExtractor()
        self._json_extractor = ATSJSONExtractor()
        self._text_extractor = TextExtractor()

        # Normalizer
        self._normalizer = NormalizationEngine(
            skill_dictionary_path=skill_dictionary_path,
            default_phone_region=default_phone_region,
        )

    def run(
        self,
        csv_path: Path | None = None,
        json_path: Path | None = None,
        text_path: Path | None = None,
        config_path: Path | None = None,
        config: OutputConfig | None = None,
    ) -> list[dict[str, Any]]:
        """Execute the full pipeline.

        Args:
            csv_path: Path to recruiter CSV file (optional).
            json_path: Path to ATS JSON file (optional).
            text_path: Path to recruiter notes TXT file (optional).
            config_path: Path to output config JSON file.
            config: Direct OutputConfig object (overrides config_path).

        Returns:
            List of projected output dicts, one per canonical candidate.

        Raises:
            ConfigLoadError: If the config file is invalid.
        """
        # --- Stage 0: Load config ---
        if config is None:
            config = self._load_config(config_path)

        # --- Stage 1-3: Parse → Extract → per source ---
        all_fragments: list[CandidateFragment] = []

        if csv_path:
            csv_fragments = self._ingest_source(
                "CSV", csv_path,
                self._csv_parser, self._csv_extractor,
            )
            all_fragments.extend(csv_fragments)

        if json_path:
            json_fragments = self._ingest_source(
                "ATS JSON", json_path,
                self._json_parser, self._json_extractor,
            )
            all_fragments.extend(json_fragments)

        if text_path:
            text_fragments = self._ingest_source(
                "Notes", text_path,
                self._text_parser, self._text_extractor,
            )
            all_fragments.extend(text_fragments)

        if not all_fragments:
            logger.warning("No fragments extracted from any source")
            return []

        logger.info(
            "Total fragments from all sources: %d", len(all_fragments)
        )

        # --- Stage 4: Normalize all fragments ---
        normalized_fragments = []
        for fragment in all_fragments:
            try:
                normalized = self._normalizer.normalize_fragment(fragment)
                if normalized.fields:
                    normalized_fragments.append(normalized)
            except Exception as e:
                logger.warning("Normalization failed for fragment: %s", e)
                # Keep the unnormalized fragment rather than losing it
                normalized_fragments.append(fragment)

        logger.info(
            "Normalized fragments: %d", len(normalized_fragments)
        )

        # --- Stage 5: Entity Resolution ---
        clusters = resolve_entities(normalized_fragments)
        logger.info(
            "Entity resolution: %d fragments → %d candidates",
            len(normalized_fragments), len(clusters),
        )

        # --- Stage 6: Merge clusters → canonical records ---
        canonical_records: list[CanonicalRecord] = []
        for cluster_indices in clusters:
            cluster_fragments = [normalized_fragments[i] for i in cluster_indices]
            try:
                record = merge_cluster(cluster_fragments)
                canonical_records.append(record)
            except Exception as e:
                logger.warning(
                    "Merge failed for cluster %s: %s", cluster_indices, e
                )
                continue

        logger.info(
            "Merged into %d canonical records", len(canonical_records)
        )

        # Sort canonical records deterministically by candidate_id
        canonical_records.sort(key=lambda r: r.candidate_id)

        # --- Stage 7-8: Project → output ---
        output = project_many(canonical_records, config)
        logger.info("Projected %d output records", len(output))

        return output

    def run_raw(
        self,
        csv_path: Path | None = None,
        json_path: Path | None = None,
        text_path: Path | None = None,
    ) -> list[CanonicalRecord]:
        """Run the pipeline up to canonical records (no projection).

        Useful for testing and inspection of the internal model.

        Returns:
            List of CanonicalRecords.
        """
        all_fragments: list[CandidateFragment] = []

        if csv_path:
            all_fragments.extend(self._ingest_source(
                "CSV", csv_path, self._csv_parser, self._csv_extractor,
            ))
        if json_path:
            all_fragments.extend(self._ingest_source(
                "ATS JSON", json_path, self._json_parser, self._json_extractor,
            ))
        if text_path:
            all_fragments.extend(self._ingest_source(
                "Notes", text_path, self._text_parser, self._text_extractor,
            ))

        if not all_fragments:
            return []

        normalized = []
        for f in all_fragments:
            try:
                n = self._normalizer.normalize_fragment(f)
                if n.fields:
                    normalized.append(n)
            except Exception:
                normalized.append(f)

        clusters = resolve_entities(normalized)

        records: list[CanonicalRecord] = []
        for cluster in clusters:
            frags = [normalized[i] for i in cluster]
            try:
                records.append(merge_cluster(frags))
            except Exception as e:
                logger.warning("Merge failed: %s", e)
                continue

        records.sort(key=lambda r: r.candidate_id)
        return records

    def _ingest_source(
        self,
        source_name: str,
        file_path: Path,
        parser: object,
        extractor: object,
    ) -> list[CandidateFragment]:
        """Ingest a single source: parse → extract.

        Graceful degradation: if parse or extraction fails, the source
        degrades to empty — other sources are unaffected.
        """
        try:
            raw_records = parser.parse(file_path)
            if not raw_records:
                logger.warning("%s source produced no records: %s", source_name, file_path)
                return []
        except (ParseError, SourceError) as e:
            logger.warning(
                "%s source degraded to empty: %s (%s)",
                source_name, file_path, e,
            )
            return []
        except Exception as e:
            logger.warning(
                "%s source unexpected error: %s (%s)",
                source_name, file_path, e,
            )
            return []

        try:
            fragments = extractor.extract(raw_records)
            logger.info(
                "%s: parsed %d records → %d fragments",
                source_name, len(raw_records), len(fragments),
            )
            return fragments
        except Exception as e:
            logger.warning(
                "%s extraction failed: %s (%s)",
                source_name, file_path, e,
            )
            return []

    @staticmethod
    def _load_config(config_path: Path | None) -> OutputConfig:
        """Load and validate output config from JSON file.

        Fails fast on config errors — config is a developer concern,
        not a data concern.
        """
        if config_path is None:
            raise ConfigLoadError("No config path provided")

        if not config_path.exists():
            raise ConfigLoadError(
                f"Config file not found: {config_path}",
                context={"file": str(config_path)},
            )

        try:
            raw = json.loads(config_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise ConfigLoadError(
                f"Invalid JSON in config: {e}",
                context={"file": str(config_path)},
            ) from e

        try:
            return OutputConfig.model_validate(raw)
        except Exception as e:
            raise ConfigLoadError(
                f"Invalid config schema: {e}",
                context={"file": str(config_path)},
            ) from e
