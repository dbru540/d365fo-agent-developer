from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

# NOTE: `graphify` is an OPTIONAL external dependency (the graph-building engine).
# It is imported lazily inside `run_graphify_staging` so that importing this module —
# and therefore the whole CLI / MCP server — never fails when graphify is absent.
# Only the `run-graphify-staging` command requires it.


def run_graphify_staging(staging_dir: str | Path, output_dir: str | Path, *, include_html: bool = True) -> dict[str, object]:
    try:
        from graphify import analyze as graph_analyze
        from graphify import build as graph_build
        from graphify import cluster as graph_cluster
        from graphify import export as graph_export
        from graphify import report as graph_report
    except ImportError as exc:  # pragma: no cover - depends on optional dep
        raise RuntimeError(
            "The 'graphify' package is required for run-graphify-staging but is not installed. "
            "Install it (pip install graphify or the project's [graph] extra) to build graph outputs. "
            "All other commands work without it."
        ) from exc

    staging_dir = Path(staging_dir).resolve()
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    inventory = json.loads((staging_dir / "graphify-staging-inventory.json").read_text(encoding="utf-8"))
    extraction = _build_extraction_from_inventory(inventory, staging_dir)
    graph = graph_build.build_from_json(extraction, directed=True)

    communities = graph_cluster.cluster(graph)
    cohesion_scores = graph_cluster.score_all(graph, communities)
    community_labels = _community_labels(graph, communities)
    god_nodes = graph_analyze.god_nodes(graph)
    surprises = graph_analyze.surprising_connections(graph, communities)

    graph_export.to_json(graph, communities, str(output_dir / "graph.json"))
    if include_html:
        try:
            graph_export.to_html(graph, communities, str(output_dir / "graph.html"), community_labels=community_labels)
        except Exception:
            pass

    report = graph_report.generate(
        graph,
        communities,
        cohesion_scores,
        community_labels,
        god_nodes,
        surprises,
        _detection_result(inventory),
        {"input": 0, "output": 0},
        root=str(staging_dir),
    )
    (output_dir / "GRAPH_REPORT.md").write_text(report, encoding="utf-8")

    manifest = {
        "staging_dir": str(staging_dir),
        "node_count": graph.number_of_nodes(),
        "edge_count": graph.number_of_edges(),
        "community_count": len(communities),
        "output_files": [name for name in ["graph.json", "GRAPH_REPORT.md", "graph.html"] if (output_dir / name).exists()],
    }
    (output_dir / "graphify-run-manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest


def _build_extraction_from_inventory(inventory: dict[str, object], staging_dir: Path) -> dict[str, object]:
    nodes: list[dict[str, object]] = []
    edges: list[dict[str, object]] = []
    seen_nodes: set[str] = set()
    artifact_by_name: dict[str, dict[str, object]] = {}

    raw_packages = staging_dir / "raw" / "packages"
    raw_artifacts = staging_dir / "raw" / "artifacts"
    artifact_id_by_type_name: dict[tuple[str, str], str] = {}

    for package in inventory["packages"]:
        package_id = f"package:{package['package_name']}"
        if package_id not in seen_nodes:
            nodes.append(
                {
                    "id": package_id,
                    "label": package["package_name"],
                    "source_file": str((raw_packages / f"{package['package_name']}.md").relative_to(staging_dir)).replace("\\", "/"),
                    "file_type": "document",
                    "node_type": "package",
                }
            )
            seen_nodes.add(package_id)

        for artifact in package["artifacts"]:
            artifact_id = f"artifact:{package['package_name']}:{artifact['artifact_type']}:{artifact['name']}"
            if artifact_id not in seen_nodes:
                nodes.append(
                    {
                        "id": artifact_id,
                        "label": artifact["name"],
                        "source_file": str((raw_artifacts / f"{package['package_name']}__{artifact['artifact_type']}__{artifact['name']}.md").relative_to(staging_dir)).replace("\\", "/"),
                        "file_type": "document",
                        "node_type": artifact["artifact_type"],
                    }
                )
                seen_nodes.add(artifact_id)
            artifact_by_name.setdefault(artifact["name"], artifact)
            artifact_id_by_type_name[(artifact["artifact_type"], artifact["name"])] = artifact_id
            edges.append({"source": package_id, "target": artifact_id, "relation": "contains", "confidence": "EXTRACTED"})
            edges[-1]["source_file"] = str((raw_packages / f"{package['package_name']}.md").relative_to(staging_dir)).replace("\\", "/")

            details = artifact.get("details", {})
            if artifact["artifact_type"] == "AxService":
                class_name = details.get("class")
                if class_name:
                    class_id = f"class:{package['package_name']}:{class_name}"
                    if class_id not in seen_nodes:
                        nodes.append(
                            {
                                "id": class_id,
                                "label": class_name,
                                "source_file": artifact["relative_path"],
                                "file_type": "document",
                                "node_type": "AxClassRef",
                            }
                        )
                        seen_nodes.add(class_id)
                    edges.append({"source": artifact_id, "target": class_id, "relation": "implemented-by", "confidence": "EXTRACTED"})
                    edges[-1]["source_file"] = artifact["relative_path"]
                for operation in details.get("operations", []):
                    operation_id = f"operation:{artifact['name']}:{operation['name']}"
                    if operation_id not in seen_nodes:
                        nodes.append(
                            {
                                "id": operation_id,
                                "label": operation["name"],
                                "source_file": artifact["relative_path"],
                                "file_type": "document",
                                "node_type": "AxServiceOperation",
                            }
                        )
                        seen_nodes.add(operation_id)
                    edges.append({"source": artifact_id, "target": operation_id, "relation": "has-operation", "confidence": "EXTRACTED"})
                    edges[-1]["source_file"] = artifact["relative_path"]

            if artifact["artifact_type"] == "AxServiceGroup":
                for service_name in details.get("services", []):
                    target_id = artifact_id_by_type_name.get(("AxService", service_name))
                    if target_id:
                        pass
                    else:
                        target_id = f"service-ref:{service_name}"
                        if target_id not in seen_nodes:
                            nodes.append(
                                {
                                    "id": target_id,
                                    "label": service_name,
                                    "source_file": artifact["relative_path"],
                                    "file_type": "document",
                                    "node_type": "AxServiceRef",
                                }
                            )
                            seen_nodes.add(target_id)
                    edges.append({"source": artifact_id, "target": target_id, "relation": "groups-service", "confidence": "EXTRACTED"})
                    edges[-1]["source_file"] = artifact["relative_path"]

            if artifact["artifact_type"] in {"AxMenuItemDisplay", "AxMenuItemAction", "AxMenuItemOutput"}:
                target_name = details.get("object")
                if target_name:
                    target_kind = (details.get("object_type") or "").lower()
                    if not target_kind and artifact["artifact_type"] == "AxMenuItemDisplay":
                        target_kind = "form"
                    if target_kind == "form":
                        target_id = f"form-ref:{target_name}"
                        relation = "targets-form"
                    elif target_kind == "class":
                        target_id = f"class-ref:{target_name}"
                        relation = "targets-class"
                    else:
                        target_id = f"object-ref:{target_name}"
                        relation = "targets-object"
                    if target_id not in seen_nodes:
                        nodes.append(
                            {
                                "id": target_id,
                                "label": target_name,
                                "source_file": artifact["relative_path"],
                                "file_type": "document",
                                "node_type": "TargetRef",
                            }
                        )
                        seen_nodes.add(target_id)
                    edges.append({"source": artifact_id, "target": target_id, "relation": relation, "confidence": "EXTRACTED", "source_file": artifact["relative_path"]})

            if artifact["artifact_type"] == "AxSecurityPrivilege":
                for entry in details.get("entry_points", []):
                    object_name = entry.get("object_name")
                    object_type = entry.get("object_type")
                    if not object_name or not object_type:
                        continue
                    target_id = artifact_id_by_type_name.get((f"Ax{object_type}", object_name))
                    if target_id is None:
                        target_id = f"security-target:{object_type}:{object_name}"
                        if target_id not in seen_nodes:
                            nodes.append(
                                {
                                    "id": target_id,
                                    "label": object_name,
                                    "source_file": artifact["relative_path"],
                                    "file_type": "document",
                                    "node_type": object_type,
                                }
                            )
                            seen_nodes.add(target_id)
                    edges.append({"source": artifact_id, "target": target_id, "relation": "grants-access-to", "confidence": "EXTRACTED", "source_file": artifact["relative_path"]})

            if artifact["artifact_type"] == "AxQuery":
                root_table = details.get("root_table")
                if root_table:
                    target_id = f"table-ref:{package['package_name']}:{root_table}"
                    if target_id not in seen_nodes:
                        nodes.append(
                            {
                                "id": target_id,
                                "label": root_table,
                                "source_file": artifact["relative_path"],
                                "file_type": "document",
                                "node_type": "AxTableRef",
                            }
                        )
                        seen_nodes.add(target_id)
                    edges.append({"source": artifact_id, "target": target_id, "relation": "queries-table", "confidence": "EXTRACTED", "source_file": artifact["relative_path"]})

            if artifact["artifact_type"] == "AxTableExtension":
                base_table = details.get("base_table")
                if base_table:
                    target_id = f"table-ref:{package['package_name']}:{base_table}"
                    if target_id not in seen_nodes:
                        nodes.append(
                            {
                                "id": target_id,
                                "label": base_table,
                                "source_file": artifact["relative_path"],
                                "file_type": "document",
                                "node_type": "AxTableRef",
                            }
                        )
                        seen_nodes.add(target_id)
                    edges.append({"source": artifact_id, "target": target_id, "relation": "extends-table", "confidence": "EXTRACTED", "source_file": artifact["relative_path"]})

            if artifact["artifact_type"] == "AxFormExtension":
                base_form = details.get("base_form")
                if base_form:
                    target_id = f"form-ref:{base_form}"
                    if target_id not in seen_nodes:
                        nodes.append(
                            {
                                "id": target_id,
                                "label": base_form,
                                "source_file": artifact["relative_path"],
                                "file_type": "document",
                                "node_type": "AxFormRef",
                            }
                        )
                        seen_nodes.add(target_id)
                    edges.append({"source": artifact_id, "target": target_id, "relation": "extends-form", "confidence": "EXTRACTED", "source_file": artifact["relative_path"]})

            if artifact["artifact_type"] == "AxDataEntityView":
                root_table = details.get("root_table")
                if root_table:
                    target_id = f"table-ref:{package['package_name']}:{root_table}"
                    if target_id not in seen_nodes:
                        nodes.append(
                            {
                                "id": target_id,
                                "label": root_table,
                                "source_file": artifact["relative_path"],
                                "file_type": "document",
                                "node_type": "AxTableRef",
                            }
                        )
                        seen_nodes.add(target_id)
                    edges.append({"source": artifact_id, "target": target_id, "relation": "entity-root-table", "confidence": "EXTRACTED", "source_file": artifact["relative_path"]})

    return {"nodes": nodes, "edges": edges, "hyperedges": [], "input_tokens": 0, "output_tokens": 0}


def _community_labels(graph, communities: dict[int, list[str]]) -> dict[int, str]:
    labels: dict[int, str] = {}
    for cid, nodes in communities.items():
        label_counter: Counter[str] = Counter()
        for node_id in nodes:
            node = graph.nodes[node_id]
            label_counter[node.get("node_type", "community")] += 1
        dominant = label_counter.most_common(1)[0][0] if label_counter else "community"
        labels[cid] = dominant
    return labels


def _detection_result(inventory: dict[str, object]) -> dict[str, object]:
    total_files = sum(package["artifact_count"] for package in inventory["packages"])
    return {"total_files": total_files, "total_words": total_files * 40}
