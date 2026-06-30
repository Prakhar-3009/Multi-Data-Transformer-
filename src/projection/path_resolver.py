"""Path resolver — resolves config paths against the canonical record.

Handles 4 path types:
1. "full_name"       → plain field access
2. "emails[0]"       → array index access
3. "skills[].name"   → array projection (map sub-field over array)
4. "location.city"   → nested object dot-access

The MISSING sentinel is critical: it distinguishes "path didn't resolve"
from "field is null." Conflating them is a subtle confident-wrong bug:
- null means "the field exists but has no value" → keep null
- MISSING means "the path doesn't exist at all" → apply on_missing strategy
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


class _Missing:
    """Sentinel for unresolved paths. Distinct from None.

    MISSING ≠ None is the single most important correctness detail
    in the projection engine. None is a legitimate resolved value
    (field is null); MISSING means the path didn't resolve at all.
    """

    _instance = None

    def __new__(cls) -> "_Missing":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "MISSING"

    def __bool__(self) -> bool:
        return False


MISSING = _Missing()

# Regex patterns for path parsing
_ARRAY_INDEX_RE = re.compile(r"^(\w+)\[(\d+)\]$")       # emails[0]
_ARRAY_PROJ_RE = re.compile(r"^(\w+)\[\]\.(.+)$")        # skills[].name
_DOT_ACCESS_RE = re.compile(r"^(\w+)\.(.+)$")            # location.city


def resolve_path(record: dict[str, Any], path: str) -> Any:
    """Resolve a config path against a canonical record dict.

    Args:
        record: The canonical record as a dict (from model_dump()).
        path: The config path to resolve.

    Returns:
        The resolved value, or MISSING if the path doesn't resolve.

    Examples:
        >>> resolve_path({"full_name": "John"}, "full_name")
        'John'
        >>> resolve_path({"emails": ["a@b.com", "c@d.com"]}, "emails[0]")
        'a@b.com'
        >>> resolve_path({"skills": [{"name": "Python"}, {"name": "ML"}]}, "skills[].name")
        ['Python', 'ML']
        >>> resolve_path({"location": {"city": "NYC"}}, "location.city")
        'NYC'
        >>> resolve_path({"full_name": None}, "full_name")
        None  # (NOT MISSING — field exists but is null)
        >>> resolve_path({}, "nonexistent")
        MISSING
    """
    if not path:
        return MISSING

    # Type 1: Array projection — "skills[].name"
    match = _ARRAY_PROJ_RE.match(path)
    if match:
        base_key, sub_path = match.group(1), match.group(2)
        return _resolve_array_projection(record, base_key, sub_path)

    # Type 2: Array index — "emails[0]"
    match = _ARRAY_INDEX_RE.match(path)
    if match:
        base_key, index = match.group(1), int(match.group(2))
        return _resolve_array_index(record, base_key, index)

    # Type 3: Dot access — "location.city"
    match = _DOT_ACCESS_RE.match(path)
    if match:
        base_key, sub_path = match.group(1), match.group(2)
        return _resolve_dot_access(record, base_key, sub_path)

    # Type 4: Plain field — "full_name"
    if path in record:
        return record[path]

    return MISSING


def _resolve_array_projection(
    record: dict, base_key: str, sub_path: str
) -> Any:
    """Resolve array projection: "skills[].name" → [skill1.name, skill2.name, ...]"""
    arr = record.get(base_key)
    if arr is None:
        return MISSING
    if not isinstance(arr, list):
        return MISSING

    result = []
    for item in arr:
        if isinstance(item, dict):
            # Support nested dot access within projection: "skills[].sources[0]"
            val = _nested_get(item, sub_path)
            if val is not MISSING:
                result.append(val)
        elif hasattr(item, sub_path):
            result.append(getattr(item, sub_path))

    return result if result else MISSING


def _resolve_array_index(
    record: dict, base_key: str, index: int
) -> Any:
    """Resolve array index: "emails[0]" → first email."""
    arr = record.get(base_key)
    if arr is None:
        return MISSING
    if not isinstance(arr, list):
        return MISSING
    if index < 0 or index >= len(arr):
        return MISSING
    return arr[index]


def _resolve_dot_access(
    record: dict, base_key: str, sub_path: str
) -> Any:
    """Resolve dot access: "location.city" → record["location"]["city"]."""
    obj = record.get(base_key)
    if obj is None:
        return MISSING

    return _nested_get(obj, sub_path)


def _nested_get(obj: Any, path: str) -> Any:
    """Recursively resolve a dot-separated path against nested dicts/objects."""
    parts = path.split(".", 1)
    key = parts[0]

    if isinstance(obj, dict):
        if key not in obj:
            return MISSING
        value = obj[key]
    elif hasattr(obj, key):
        value = getattr(obj, key)
    else:
        return MISSING

    if len(parts) == 1:
        return value

    # Recurse into nested path
    return _nested_get(value, parts[1])
