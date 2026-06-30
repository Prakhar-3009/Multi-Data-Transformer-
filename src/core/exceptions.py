"""Custom exception hierarchy for the candidate transformer pipeline.

Design principle: data problems degrade gracefully (null/skip/log),
config problems fail fast (raise). This split is intentional —
bad data is expected and absorbed; bad config is a developer error
that should surface immediately.

Exception hierarchy:
    TransformerError (base)
    ├── SourceError (data problems — caught and degraded)
    │   ├── ParseError
    │   └── ExtractionError
    ├── NormalizationError (data — caught, field → null)
    ├── ValidationError (data — caught, field → null + confidence 0)
    ├── ResolutionError (data — caught, fragments kept separate)
    ├── MergeError (data — caught, best-effort merge)
    ├── ConfigError (config problems — NOT caught, fail fast)
    │   ├── ConfigLoadError
    │   ├── ConfigPathError
    │   └── ConfigProjectionError
    └── PipelineError (fatal — unexpected system error)
"""


class TransformerError(Exception):
    """Base exception for all transformer pipeline errors."""

    def __init__(self, message: str, context: dict | None = None) -> None:
        self.context = context or {}
        super().__init__(message)


# --- Data problems: caught and degraded gracefully ---


class SourceError(TransformerError):
    """Error during source ingestion (file read, parse, extraction).

    These are EXPECTED — sources are unreliable by nature.
    Handler: degrade the source to empty, continue with other sources.
    """


class ParseError(SourceError):
    """Failed to parse a source file (corrupt JSON, malformed CSV, etc.).

    Handler: entire source degrades to empty. Pipeline continues.
    """


class ExtractionError(SourceError):
    """Failed to extract a field from a parsed source.

    Handler: field → null, low confidence. Other fields unaffected.
    """


class NormalizationError(TransformerError):
    """Failed to normalize a field value (un-parseable phone, invalid date, etc.).

    Handler: field → null, confidence → 0. Value does not enter merge.
    """


class ValidationError(TransformerError):
    """Field value failed semantic validation after normalization.

    Handler: field → null, validation_score → 0. Value cannot win merge.
    """


class ResolutionError(TransformerError):
    """Error during entity resolution / matching.

    Handler: affected fragments kept as separate candidates (don't force-merge).
    A wrong merge is worse than a missed merge.
    """


class MergeError(TransformerError):
    """Error during merge / conflict resolution.

    Handler: best-effort merge, log the error. Affected field → null if
    no safe winner can be determined.
    """


# --- Config problems: NOT caught, fail fast ---


class ConfigError(TransformerError):
    """Base for configuration errors. These are developer errors.

    NOT caught by the pipeline — they propagate to the CLI and stop execution.
    A bad config should be fixed, not absorbed.
    """


class ConfigLoadError(ConfigError):
    """Failed to load or parse the config file."""


class ConfigPathError(ConfigError):
    """A 'from' path in the config references an invalid path pattern."""


class ConfigProjectionError(ConfigError):
    """A required field is missing under 'error' strategy.

    This is the ONLY config error that can occur at projection time
    (all others are caught at config load). It means the canonical record
    doesn't have a value that the config declared as required + error.
    """


# --- Fatal / unexpected ---


class PipelineError(TransformerError):
    """Unexpected system error during pipeline execution.

    This indicates a bug in the pipeline code, not a data or config problem.
    Should never occur in production — if it does, it's a code defect.
    """
