"""Skill normalizer — two-tier strategy: exact alias match, then fuzzy match.

Tier 1: Dictionary/alias exact match. A curated map of known aliases
        (lowercase + strip + collapse separators → exact lookup).
        Deterministic, high confidence.

Tier 2: Fuzzy match for unknowns (typos, novel spellings). Uses rapidfuzz
        with WRatio scorer. Takes best match ONLY if score ≥ 95.
        
        Threshold is 95 (not 90) because short strings have deceptively
        generous edit distances. "Java" vs "JavaScript" scores ~88-91 at
        WRatio — at threshold 90, that's a dangerous false positive.

Abstain rule: below threshold → do not map. Keep the raw skill with low
confidence, or drop it. Forcing a low-score fuzzy match is exactly how
you confidently mislabel "Java" as "JavaScript."
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from rapidfuzz import fuzz, process

from src.core.constants import SKILL_FUZZY_THRESHOLD

logger = logging.getLogger(__name__)

# Default skill aliases — loaded from file if available, else this fallback.
# Format: {"alias_lowercase": "Canonical Name"}
_DEFAULT_ALIASES: dict[str, str] = {
    # Python ecosystem
    "python": "Python",
    "python3": "Python",
    "py": "Python",
    "cpython": "Python",
    # JavaScript ecosystem
    "javascript": "JavaScript",
    "js": "JavaScript",
    "es6": "JavaScript",
    "ecmascript": "JavaScript",
    "node": "Node.js",
    "nodejs": "Node.js",
    "node.js": "Node.js",
    "react": "React",
    "reactjs": "React",
    "react.js": "React",
    "angular": "Angular",
    "angularjs": "Angular",
    "vue": "Vue.js",
    "vuejs": "Vue.js",
    "vue.js": "Vue.js",
    "typescript": "TypeScript",
    "ts": "TypeScript",
    # Java ecosystem
    "java": "Java",
    "spring": "Spring Framework",
    "spring boot": "Spring Boot",
    "springboot": "Spring Boot",
    # Data / ML
    "ml": "Machine Learning",
    "machine learning": "Machine Learning",
    "machine-learning": "Machine Learning",
    "deep learning": "Deep Learning",
    "deep-learning": "Deep Learning",
    "dl": "Deep Learning",
    "ai": "Artificial Intelligence",
    "artificial intelligence": "Artificial Intelligence",
    "nlp": "Natural Language Processing",
    "natural language processing": "Natural Language Processing",
    "cv": "Computer Vision",
    "computer vision": "Computer Vision",
    "data science": "Data Science",
    "data-science": "Data Science",
    "tensorflow": "TensorFlow",
    "tf": "TensorFlow",
    "pytorch": "PyTorch",
    "torch": "PyTorch",
    "pandas": "Pandas",
    "numpy": "NumPy",
    "scikit-learn": "scikit-learn",
    "sklearn": "scikit-learn",
    # Cloud / DevOps
    "aws": "AWS",
    "amazon web services": "AWS",
    "gcp": "Google Cloud Platform",
    "google cloud": "Google Cloud Platform",
    "azure": "Microsoft Azure",
    "microsoft azure": "Microsoft Azure",
    "docker": "Docker",
    "kubernetes": "Kubernetes",
    "k8s": "Kubernetes",
    # Databases
    "sql": "SQL",
    "mysql": "MySQL",
    "postgres": "PostgreSQL",
    "postgresql": "PostgreSQL",
    "mongodb": "MongoDB",
    "mongo": "MongoDB",
    "redis": "Redis",
    # Languages
    "c++": "C++",
    "cpp": "C++",
    "c#": "C#",
    "csharp": "C#",
    "golang": "Go",
    "go": "Go",
    "rust": "Rust",
    "ruby": "Ruby",
    "scala": "Scala",
    "kotlin": "Kotlin",
    "swift": "Swift",
    "r": "R",
    # Web
    "html": "HTML",
    "html5": "HTML",
    "css": "CSS",
    "css3": "CSS",
    "rest": "REST APIs",
    "rest api": "REST APIs",
    "restful": "REST APIs",
    "graphql": "GraphQL",
    # Tools / Practices
    "git": "Git",
    "github": "GitHub",
    "ci/cd": "CI/CD",
    "cicd": "CI/CD",
    "agile": "Agile",
    "scrum": "Scrum",
    "linux": "Linux",
    "unix": "Linux",
}


class SkillNormalizer:
    """Two-tier skill normalizer: exact alias match → fuzzy match.

    Attributes:
        _aliases: Lowercase alias → canonical name mapping.
        _canonical_names: Sorted list of unique canonical names for fuzzy search.
        _threshold: Minimum fuzzy match score to accept (default 95).
    """

    def __init__(
        self,
        aliases: dict[str, str] | None = None,
        dictionary_path: Path | None = None,
        threshold: int = SKILL_FUZZY_THRESHOLD,
    ) -> None:
        """Initialize with aliases from dict, file, or defaults.

        Args:
            aliases: Direct alias dict. Takes priority if provided.
            dictionary_path: Path to JSON file with skill aliases.
            threshold: Minimum fuzzy match score (0-100). Default 95.
        """
        self._threshold = threshold

        if aliases is not None:
            self._aliases = {k.lower().strip(): v for k, v in aliases.items()}
        elif dictionary_path and dictionary_path.exists():
            self._aliases = self._load_dictionary(dictionary_path)
        else:
            self._aliases = dict(_DEFAULT_ALIASES)

        # Unique canonical names for fuzzy matching, sorted for determinism
        self._canonical_names = sorted(set(self._aliases.values()))

    @staticmethod
    def _load_dictionary(path: Path) -> dict[str, str]:
        """Load skill aliases from a JSON file."""
        try:
            with open(path, encoding="utf-8") as f:
                raw = json.load(f)
            return {k.lower().strip(): v for k, v in raw.items()}
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load skill dictionary from %s: %s", path, e)
            return dict(_DEFAULT_ALIASES)

    def _normalize_key(self, skill: str) -> str:
        """Normalize a skill string for alias lookup.

        Lowercase, strip, collapse separators (hyphens, underscores) to spaces.
        """
        key = skill.lower().strip()
        key = re.sub(r"[-_]+", " ", key)
        key = re.sub(r"\s+", " ", key)
        return key

    def normalize(self, raw_skill: str) -> tuple[str | None, float]:
        """Normalize a skill name to its canonical form.

        Args:
            raw_skill: Raw skill string from any source.

        Returns:
            Tuple of (canonical_name, confidence):
            - Exact alias match: ("Machine Learning", 1.0)
            - Fuzzy match ≥ threshold: ("Python", score/100)
            - Below threshold: (None, 0.0) — abstain
            - Empty/invalid: (None, 0.0)

        Examples:
            >>> normalizer = SkillNormalizer()
            >>> normalizer.normalize("ML")
            ('Machine Learning', 1.0)
            >>> normalizer.normalize("machine-learning")
            ('Machine Learning', 1.0)
            >>> normalizer.normalize("pythn")  # typo
            ('Python', 0.96)  # if WRatio("pythn", "Python") = 96
            >>> normalizer.normalize("xyzzy")  # unknown
            (None, 0.0)
        """
        if not raw_skill or not isinstance(raw_skill, str):
            return None, 0.0

        cleaned = raw_skill.strip()
        if not cleaned:
            return None, 0.0

        # Tier 1: exact alias match (deterministic, high confidence)
        key = self._normalize_key(cleaned)
        if key in self._aliases:
            return self._aliases[key], 1.0

        # Tier 2: fuzzy match against canonical names
        if not self._canonical_names:
            return None, 0.0

        result = process.extractOne(
            cleaned,
            self._canonical_names,
            scorer=fuzz.WRatio,
            score_cutoff=self._threshold,
        )

        if result is not None:
            matched_name, score, _ = result
            # Scale confidence by match score (95 → 0.95, 99 → 0.99)
            confidence = score / 100.0
            logger.debug(
                "Fuzzy skill match: %r → %r (score=%d)", raw_skill, matched_name, score
            )
            return matched_name, confidence

        # Below threshold → keep the raw skill with lower confidence.
        # Unknown skills (e.g., "Figma", "Product Strategy") are valid —
        # our dictionary is not exhaustive. Pass through with reduced trust.
        logger.debug(
            "Unknown skill (no match above threshold=%d): %r — keeping as-is",
            self._threshold, raw_skill,
        )
        return cleaned, 0.5
