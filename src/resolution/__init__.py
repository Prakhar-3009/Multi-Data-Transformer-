"""Resolution package — entity resolution + merge engine."""

from src.resolution.entity_resolver import resolve_entities
from src.resolution.merge import merge_cluster

__all__ = [
    "resolve_entities",
    "merge_cluster",
]
