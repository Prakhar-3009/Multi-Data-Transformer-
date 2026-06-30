"""CLI entry point — minimal argparse interface.

The assignment explicitly says CLI is "completely sufficient" and
"don't spend time on polish." This is ~40 lines of argparse wiring
that runs the pipeline end-to-end.

Usage:
    python -m src.cli \
        --csv data/sample_inputs/candidates.csv \
        --json data/sample_inputs/ats_candidates.json \
        --text data/sample_inputs/recruiter_notes.txt \
        --config data/configs/default_config.json \
        --output output.json
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from src.core.pipeline import Pipeline


def main() -> None:
    """Run the candidate data transformer pipeline."""
    parser = argparse.ArgumentParser(
        description="Multi-Source Candidate Data Transformer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python -m src.cli --csv data/sample_inputs/candidates.csv "
            "--json data/sample_inputs/ats_candidates.json "
            "--text data/sample_inputs/recruiter_notes.txt "
            "--config data/configs/default_config.json\n"
            "\n"
            "  python -m src.cli --csv data/sample_inputs/candidates.csv "
            "--config data/configs/custom_config.json --output custom_output.json"
        ),
    )

    parser.add_argument(
        "--csv", type=Path, default=None,
        help="Path to recruiter CSV file",
    )
    parser.add_argument(
        "--json", type=Path, default=None,
        help="Path to ATS JSON file",
    )
    parser.add_argument(
        "--text", type=Path, default=None,
        help="Path to recruiter notes TXT file",
    )
    parser.add_argument(
        "--config", type=Path, required=True,
        help="Path to output configuration JSON file",
    )
    parser.add_argument(
        "--output", "-o", type=Path, default=None,
        help="Output file path (default: stdout)",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable verbose/debug logging",
    )

    args = parser.parse_args()

    # Configure logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Validate at least one source provided
    if not any([args.csv, args.json, args.text]):
        parser.error("At least one source (--csv, --json, --text) is required")

    # Run the pipeline
    try:
        pipeline = Pipeline()
        results = pipeline.run(
            csv_path=args.csv,
            json_path=args.json,
            text_path=args.text,
            config_path=args.config,
        )

        # Format output
        output_json = json.dumps(results, indent=2, ensure_ascii=False, default=str)

        if args.output:
            args.output.write_text(output_json, encoding="utf-8")
            logging.getLogger(__name__).info(
                "Output written to %s (%d candidates)",
                args.output, len(results),
            )
        else:
            print(output_json)

    except Exception as e:
        logging.getLogger(__name__).error("Pipeline failed: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
