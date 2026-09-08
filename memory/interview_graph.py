"""
CandidateGraph — a lightweight, in-process typed-edge graph linking topics,
questions, and answer-bank entries for a single candidate.

Adapted from cognitiveBrain's InProcessGraph pattern (docs/packages/cognitiveBrain/
memory/src/core/graph/InProcessGraph.ts — real, verified code, not the
aspirational Neo4j/pgvector adapters from that package's design doc), but
scoped down to the four edge types this domain needs. Per-candidate scale is
hundreds of nodes/edges, not millions, so a plain adjacency list serialized
to graph.json is the right size — no graph database.
"""

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal, Optional

logger = logging.getLogger(__name__)

EdgeType = Literal["tests_topic", "grounded_by", "related_to", "similar_to"]


@dataclass
class GraphEdge:
    source: str
    target: str
    edge_type: EdgeType
    weight: float = 1.0


class CandidateGraph:
    def __init__(self, path: Path):
        self.path = path
        self.edges: list[GraphEdge] = self._load()

    def _load(self) -> list[GraphEdge]:
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return [GraphEdge(**e) for e in data.get("edges", [])]
        except Exception as e:
            logger.error(f"CandidateGraph._load failed: {e}")
            return []

    def save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        try:
            tmp.write_text(
                json.dumps({"edges": [asdict(e) for e in self.edges]}, indent=2),
                encoding="utf-8",
            )
            tmp.replace(self.path)
        except Exception as e:
            tmp.unlink(missing_ok=True)
            logger.error(f"CandidateGraph.save failed: {e}")
            raise

    def add_edge(
        self, source: str, target: str, edge_type: EdgeType, weight: float = 1.0
    ) -> None:
        """Idempotent — re-adding an existing edge bumps its weight rather than duplicating."""
        for e in self.edges:
            if e.source == source and e.target == target and e.edge_type == edge_type:
                e.weight = max(e.weight, weight)
                return
        self.edges.append(GraphEdge(source, target, edge_type, weight))

    def remove_node(self, node_id: str) -> None:
        """Drop every edge touching a deleted node (e.g. a removed answer-bank entry)."""
        self.edges = [e for e in self.edges if e.source != node_id and e.target != node_id]

    def neighbors(self, node_id: str, edge_type: Optional[EdgeType] = None) -> list[str]:
        return [
            e.target
            for e in self.edges
            if e.source == node_id and (edge_type is None or e.edge_type == edge_type)
        ]

    def related_topics(self, topic: str, min_weight: float = 0.0) -> list[str]:
        return [
            e.target
            for e in self.edges
            if e.source == topic and e.edge_type == "related_to" and e.weight >= min_weight
        ]

    def record_topic_co_occurrence(self, topics: list[str], weight: float = 0.3) -> None:
        """Bidirectional related_to edges between topics answered in the same question —
        mirrors InProcessGraph.inferTypedEdges()'s co-occurrence-to-typed-edge rule."""
        unique = sorted(set(topics))
        for i, a in enumerate(unique):
            for b in unique[i + 1 :]:
                self.add_edge(a, b, "related_to", weight)
                self.add_edge(b, a, "related_to", weight)
