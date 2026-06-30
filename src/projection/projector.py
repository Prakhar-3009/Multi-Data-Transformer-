"""Projector — config-driven output reshaping engine (the "twist").

Takes a CanonicalRecord + OutputConfig and produces a projected output
dict shaped exactly as the config specifies. This is the headline feature:
same engine, same data, different configs → different output shapes,
with zero code changes.

Algorithm:
1. Serialize canonical record to dict
2. For each field spec in config:
   a. Resolve the 'from' path against the record
   b. Handle MISSING values via on_missing strategy
   c. Apply per-field normalization override if specified
   d. Assign to output with the config-specified key name
3. Toggle confidence/provenance based on config flags
4. Return the projected dict

Design splits:
- Data problems (MISSING path → null/omit): degrade gracefully
- Config problems (invalid path pattern): fail fast at load time
- Required field under 'error' strategy: raise ConfigProjectionError
"""

from __future__ import annotations

import logging
from typing import Any

from src.core.exceptions import ConfigProjectionError
from src.models.canonical import CanonicalRecord
from src.models.config import OutputConfig
from src.projection.path_resolver import MISSING, resolve_path

logger = logging.getLogger(__name__)


def project(
    record: CanonicalRecord,
    config: OutputConfig,
) -> dict[str, Any]:
    """Project a canonical record into a config-shaped output dict.

    Args:
        record: The internal canonical record (full, clean, merged).
        config: The output configuration specifying the desired shape.

    Returns:
        Dict shaped according to the config, ready for JSON serialization.

    Raises:
        ConfigProjectionError: If a required field is MISSING under
                               "error" strategy.
    """
    # Serialize to dict for path resolution
    record_dict = record.model_dump(mode="python")

    output: dict[str, Any] = {}

    for field_spec in config.fields:
        from_path = field_spec.resolved_from
        out_name = field_spec.path

        # Resolve the value from the canonical record
        value = resolve_path(record_dict, from_path)

        # Handle MISSING values
        if value is MISSING:
            strategy = field_spec.on_missing or config.on_missing

            if strategy == "error" and field_spec.required:
                raise ConfigProjectionError(
                    f"Required field '{out_name}' (from '{from_path}') "
                    f"is missing in canonical record for candidate "
                    f"'{record.candidate_id}'",
                    context={
                        "field": out_name,
                        "from": from_path,
                        "candidate_id": record.candidate_id,
                    },
                )
            elif strategy == "omit":
                continue  # Skip this field entirely
            else:
                # "null" strategy (default)
                value = None

        # Assign to output
        output[out_name] = value

    # Toggle metadata based on config flags
    if config.include_confidence:
        output["overall_confidence"] = record.overall_confidence

    if config.include_provenance:
        output["provenance"] = [
            entry.model_dump(mode="python") for entry in record.provenance
        ]

    return output


def project_many(
    records: list[CanonicalRecord],
    config: OutputConfig,
) -> list[dict[str, Any]]:
    """Project multiple canonical records.

    Handles per-record projection errors gracefully: a failed projection
    for one record doesn't stop processing of others.

    Args:
        records: List of canonical records.
        config: Output configuration.

    Returns:
        List of projected output dicts. May be shorter than input
        if some records failed projection under 'error' strategy.
    """
    results: list[dict[str, Any]] = []

    for record in records:
        try:
            projected = project(record, config)
            results.append(projected)
        except ConfigProjectionError as e:
            logger.warning(
                "Projection failed for candidate %s: %s",
                record.candidate_id, e,
            )
            # Under 'error' strategy, skip the record
            continue

    return results
