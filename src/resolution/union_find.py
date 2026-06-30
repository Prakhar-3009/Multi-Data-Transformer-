"""Union-Find (Disjoint Set Union) data structure for entity resolution.

Used to maintain transitive closure during entity matching: if fragment A
matches B (via email) and B matches C (via phone), then A, B, and C are
all the same person. Union-Find handles this efficiently with path
compression and union by rank.

Time complexity: amortized O(α(n)) per operation, where α is the
inverse Ackermann function — effectively O(1).
"""

from __future__ import annotations


class UnionFind:
    """Disjoint Set Union with path compression and union by rank.

    Attributes:
        _parent: Maps each element to its parent in the tree.
        _rank: Maps each element to its rank (tree height upper bound).
    """

    def __init__(self) -> None:
        self._parent: dict[int, int] = {}
        self._rank: dict[int, int] = {}

    def find(self, x: int) -> int:
        """Find the root representative of the set containing x.

        Uses path compression: all nodes along the path to the root
        are directly linked to the root, flattening the tree.

        Args:
            x: Element to find the root of.

        Returns:
            Root representative of x's set.
        """
        if x not in self._parent:
            self._parent[x] = x
            self._rank[x] = 0
            return x

        # Path compression: iterative for stack safety
        root = x
        while self._parent[root] != root:
            root = self._parent[root]

        # Compress path: point all nodes directly to root
        current = x
        while current != root:
            next_parent = self._parent[current]
            self._parent[current] = root
            current = next_parent

        return root

    def union(self, x: int, y: int) -> bool:
        """Merge the sets containing x and y.

        Uses union by rank: the shorter tree is attached under the
        taller tree's root, keeping the structure flat.

        Args:
            x: First element.
            y: Second element.

        Returns:
            True if x and y were in different sets (merge happened).
            False if they were already in the same set.
        """
        root_x = self.find(x)
        root_y = self.find(y)

        if root_x == root_y:
            return False  # Already same set

        # Union by rank: attach shorter tree under taller tree
        if self._rank[root_x] < self._rank[root_y]:
            self._parent[root_x] = root_y
        elif self._rank[root_x] > self._rank[root_y]:
            self._parent[root_y] = root_x
        else:
            self._parent[root_y] = root_x
            self._rank[root_x] += 1

        return True

    def connected(self, x: int, y: int) -> bool:
        """Check if x and y are in the same set."""
        return self.find(x) == self.find(y)

    def get_clusters(self, elements: list[int]) -> dict[int, list[int]]:
        """Get all clusters (groups of connected elements).

        Args:
            elements: List of all element IDs.

        Returns:
            Dict mapping root representative → list of elements in that cluster.
        """
        clusters: dict[int, list[int]] = {}
        for elem in elements:
            root = self.find(elem)
            if root not in clusters:
                clusters[root] = []
            clusters[root].append(elem)
        return clusters
