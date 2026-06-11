from __future__ import annotations

import json
from pathlib import Path


def discover_graph_path(repo_root: str | Path) -> Path | None:
    repo_root = Path(repo_root).resolve()
    for current in [repo_root, *repo_root.parents]:
        omx_dir = current / ".omx"
        if not omx_dir.exists():
            continue
        candidates = sorted(omx_dir.glob("graphify-run-*/graph.json"), key=lambda path: path.stat().st_mtime, reverse=True)
        if candidates:
            return candidates[0]
    return None


class GraphIndex:
    def __init__(self, graph_path: str | Path) -> None:
        self.graph_path = Path(graph_path)
        payload = json.loads(self.graph_path.read_text(encoding="utf-8"))
        self.nodes = payload.get("nodes", [])
        self.links = payload.get("links", [])
        self._nodes_by_id = {node["id"]: node for node in self.nodes}
        self._nodes_by_label = {}
        self._staging_dir = self._discover_staging_dir()
        for node in self.nodes:
            self._nodes_by_label.setdefault(node.get("label"), []).append(node)

    def related_artifact_labels(self, label: str, limit: int = 10) -> list[str]:
        seed_nodes = self._nodes_by_label.get(label, [])
        if not seed_nodes:
            return []
        seed_ids = {node["id"] for node in seed_nodes}
        related_ids: set[str] = set(seed_ids)
        for edge in self.links:
            if edge.get("source") in seed_ids:
                related_ids.add(edge.get("target"))
            if edge.get("target") in seed_ids:
                related_ids.add(edge.get("source"))

        labels = []
        seen = set()
        for node_id in related_ids:
            node = self._nodes_by_id.get(node_id)
            if not node:
                continue
            node_label = node.get("label")
            if not node_label or node_label in seen:
                continue
            seen.add(node_label)
            labels.append(node_label)
        labels.sort()
        return labels[:limit]

    def related_nodes(self, label: str, limit: int = 10) -> list[dict[str, object]]:
        labels = self.related_artifact_labels(label, limit=limit)
        results = []
        for related_label in labels:
            node = self._nodes_by_label.get(related_label, [{}])[0]
            if node:
                results.append(node)
        return results

    def related_label_set(self, label: str, limit: int = 25) -> set[str]:
        return set(self.related_artifact_labels(label, limit=limit))

    def materialize_related_examples(self, label: str, limit: int = 5) -> list[dict[str, object]]:
        examples: list[dict[str, object]] = []
        if not self._staging_dir:
            return examples
        for node in self.related_nodes(label, limit=limit):
            source_file = node.get("source_file")
            if not source_file:
                continue
            source_path = self._staging_dir / source_file
            if not source_path.exists():
                continue
            examples.append(
                {
                    "artifact": {
                        "name": node.get("label"),
                        "artifact_type": node.get("node_type"),
                        "model": None,
                        "package": None,
                        "classification": "graph-derived",
                        "relative_path": source_file,
                        "label": None,
                        "is_public": False,
                        "data_management_enabled": False,
                        "public_entity_name": None,
                        "public_collection_name": None,
                    },
                    "content": source_path.read_text(encoding="utf-8", errors="ignore"),
                    "source": "graph",
                }
            )
        return examples

    def _discover_staging_dir(self) -> Path | None:
        manifest_path = self.graph_path.parent / "graphify-run-manifest.json"
        if not manifest_path.exists():
            return None
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        staging_dir = payload.get("staging_dir")
        return Path(staging_dir) if staging_dir else None
