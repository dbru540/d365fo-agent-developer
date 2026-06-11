from __future__ import annotations

import re
import zipfile
from collections import Counter
from pathlib import Path
from xml.etree import ElementTree as ET

from d365fo_agent.models import Artifact, Catalog, Relation
from d365fo_agent.rules import CorpusRules


# The custom source tree (src/xplusplus/models) is parsed for EVERY AOT type, not a whitelist:
# any folder named "Ax<Type>" is an element folder (AxEnum, AxEdt, AxDataEntityViewExtension,
# AxWorkflowApproval, AxTile, …). A whitelist here silently dropped custom enums/EDTs/extensions
# from `src`; the "Ax*" rule mirrors the standard scanner and needs no upkeep for new types.

EXTENSION_OF_PATTERN = re.compile(
    r"ExtensionOf\(\s*(?:tableStr|classStr|formStr|queryStr|menuItemDisplayStr|menuItemActionStr|menuItemOutputStr|dataEntityViewStr|viewStr)\((?P<name>[A-Za-z0-9_]+)\)\s*\)",
    re.IGNORECASE,
)
REPORT_QUERY_PATTERN = re.compile(r"SELECT\s+\*\s+FROM\s+(?P<provider>[A-Za-z0-9_]+)\.[A-Za-z0-9_]+", re.IGNORECASE)


def build_catalog(repo_root: str | Path, rules: CorpusRules) -> Catalog:
    repo_root = Path(repo_root)
    catalog = Catalog()
    relation_keys: set[tuple[str, str, str, str, str]] = set()

    models_root = repo_root / "src" / "xplusplus" / "models"
    for model_dir in sorted(path for path in models_root.iterdir() if path.is_dir()):
        descriptor = _load_model_descriptor(model_dir)
        if not descriptor:
            continue
        model_name, module_references = descriptor
        catalog.models.append(model_name)
        for reference in module_references:
            _add_relation(
                catalog,
                relation_keys,
                Relation(
                    relation_type="belongs-to-package",
                    source=model_name,
                    target=reference,
                    model=model_name,
                    relative_path=str((model_dir / "Descriptor").relative_to(repo_root)).replace("\\", "/"),
                ),
            )

        for package_dir in sorted(path for path in model_dir.iterdir() if path.is_dir() and path.name != "Descriptor"):
            for xml_file in sorted(package_dir.rglob("*.xml")):
                artifact_type = xml_file.parent.name
                if not artifact_type.startswith("Ax"):
                    continue
                artifact, relations = _parse_artifact(repo_root, model_name, package_dir.name, xml_file, rules)
                catalog.artifacts.append(artifact)
                _add_relation(
                    catalog,
                    relation_keys,
                    Relation(
                        relation_type="belongs-to-model",
                        source=artifact.name,
                        target=model_name,
                        model=model_name,
                        relative_path=artifact.relative_path,
                    ),
                )
                for relation in relations:
                    _add_relation(catalog, relation_keys, relation)

        for xref_file in sorted(model_dir.glob("*.xref")):
            for relation in _parse_xref(repo_root, model_name, xref_file):
                _add_relation(catalog, relation_keys, relation)

    catalog.models.sort()
    return catalog


def summarize_classifications(catalog: Catalog) -> dict[str, int]:
    counter = Counter(artifact.classification for artifact in catalog.artifacts)
    return dict(sorted(counter.items()))


def find_artifacts(catalog: Catalog, name: str, artifact_type: str | None = None) -> list[Artifact]:
    lowered_name = name.lower()
    matches = [
        artifact
        for artifact in catalog.artifacts
        if lowered_name in artifact.name.lower() and (artifact_type is None or artifact.artifact_type == artifact_type)
    ]
    return sorted(matches, key=lambda artifact: (artifact.name.lower() != lowered_name, artifact.name.lower()))


def get_artifact_details(catalog: Catalog, name: str) -> dict[str, object]:
    matches = find_artifacts(catalog, name)
    if not matches:
        return {"artifact": None, "relations": []}
    artifact = matches[0]
    relations = [
        relation.to_dict()
        for relation in catalog.relations
        if relation.source == artifact.name or relation.target == artifact.name
    ]
    return {"artifact": artifact.to_dict(), "relations": relations}


def find_references(repo_root: str | Path, symbol: str) -> list[dict[str, object]]:
    repo_root = Path(repo_root)
    matches: list[dict[str, object]] = []
    for path in sorted(repo_root.rglob("*.xml")):
        text = path.read_text(encoding="utf-8", errors="ignore")
        for line_number, line in enumerate(text.splitlines(), start=1):
            if symbol in line:
                matches.append(
                    {
                        "path": str(path.relative_to(repo_root)).replace("\\", "/"),
                        "line_number": line_number,
                        "line": line.strip(),
                    }
                )
    return matches


def find_reverse_references(catalog: Catalog, symbol: str) -> list[dict[str, object]]:
    return [
        relation.to_dict()
        for relation in catalog.relations
        if relation.relation_type.startswith("xref:") and relation.target == symbol
    ]


def _load_model_descriptor(model_dir: Path) -> tuple[str, list[str]] | None:
    descriptor_dir = model_dir / "Descriptor"
    if not descriptor_dir.exists():
        return None
    candidates = sorted(descriptor_dir.glob("*.xml"))
    if not candidates:
        return None
    root = ET.fromstring(candidates[0].read_text(encoding="utf-8"))
    model_name = _find_text(root, "Name") or candidates[0].stem
    module_references = [element.text.strip() for element in root.iter() if _local_name(element.tag) == "string" and element.text]
    return model_name, module_references


def _parse_artifact(
    repo_root: Path,
    model_name: str,
    package_name: str,
    path: Path,
    rules: CorpusRules,
) -> tuple[Artifact, list[Relation]]:
    root = ET.fromstring(path.read_text(encoding="utf-8"))
    name = _find_text(root, "Name") or path.stem
    relative_path = str(path.relative_to(repo_root)).replace("\\", "/")
    classification = rules.classify(model_name, relative_path)
    label = _find_text(root, "Label")
    is_public = (_find_text(root, "IsPublic") or "").lower() == "yes"
    data_management_enabled = (_find_text(root, "DataManagementEnabled") or "").lower() == "yes"
    artifact = Artifact(
        name=name,
        artifact_type=path.parent.name,
        model=model_name,
        package=package_name,
        classification=classification,
        relative_path=relative_path,
        label=label,
        is_public=is_public,
        data_management_enabled=data_management_enabled,
        public_entity_name=_find_text(root, "PublicEntityName"),
        public_collection_name=_find_text(root, "PublicCollectionName"),
    )

    relations: list[Relation] = []
    if label:
        relations.append(Relation("uses-label", artifact.name, label, model_name, relative_path))
    if artifact.public_entity_name:
        relations.append(Relation("exposed-as-entity", artifact.name, artifact.public_entity_name, model_name, relative_path))
    if artifact.public_collection_name:
        relations.append(
            Relation("exposed-as-public-collection", artifact.name, artifact.public_collection_name, model_name, relative_path)
        )

    if artifact.artifact_type == "AxClass":
        declaration = _find_text(root, "Declaration") or ""
        match = EXTENSION_OF_PATTERN.search(declaration)
        if match:
            relations.append(Relation("extension-of", artifact.name, match.group("name"), model_name, relative_path))

    if artifact.artifact_type == "AxTableExtension" and "." in artifact.name:
        relations.append(Relation("extension-of", artifact.name, artifact.name.split(".", 1)[0], model_name, relative_path))
        for element in root.iter():
            if _local_name(element.tag) == "RelatedTable" and element.text:
                relations.append(Relation("related-table", artifact.name, element.text.strip(), model_name, relative_path))
    elif artifact.artifact_type.endswith("Extension") and "." in artifact.name:
        # Any other extension (AxEnumExtension, AxEdtExtension, AxDataEntityViewExtension,
        # AxMenuExtension, AxViewExtension, …) targets the base named before the '.'.
        relations.append(Relation("extension-of", artifact.name, artifact.name.split(".", 1)[0], model_name, relative_path))

    if artifact.artifact_type == "AxSecurityPrivilege":
        for entry in _children_by_local_name(root, "AxSecurityEntryPointReference"):
            object_name = _find_text(entry, "ObjectName")
            object_type = _find_text(entry, "ObjectType")
            if object_name and object_type:
                relations.append(
                    Relation("secured-by", artifact.name, f"{object_type}:{object_name}", model_name, relative_path)
                )

    if artifact.artifact_type == "AxReport":
        for element in root.iter():
            if _local_name(element.tag) != "Query" or not element.text:
                continue
            match = REPORT_QUERY_PATTERN.search(element.text.strip())
            if match:
                relations.append(Relation("related-to-report", artifact.name, match.group("provider"), model_name, relative_path))

    return artifact, relations


def _parse_xref(repo_root: Path, model_name: str, path: Path) -> list[Relation]:
    relations: list[Relation] = []
    relative_path = str(path.relative_to(repo_root)).replace("\\", "/")
    with zipfile.ZipFile(path) as archive:
        if "ElementReferences" not in archive.namelist():
            return relations
        payload = archive.read("ElementReferences").decode("utf-16le", errors="ignore")
        for raw_line in payload.splitlines():
            if not raw_line.strip():
                continue
            parts = raw_line.split("|")
            if len(parts) < 3:
                continue
            source, target, relation_type = parts[:3]
            relations.append(
                Relation(
                    relation_type=f"xref:{relation_type}",
                    source=source,
                    target=target,
                    model=model_name,
                    relative_path=relative_path,
                )
            )
    return relations


def _add_relation(catalog: Catalog, seen: set[tuple[str, str, str, str, str]], relation: Relation) -> None:
    key = (relation.relation_type, relation.source, relation.target, relation.model, relation.relative_path)
    if key in seen:
        return
    seen.add(key)
    catalog.relations.append(relation)


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _find_text(root: ET.Element, local_name: str) -> str | None:
    for element in root.iter():
        if _local_name(element.tag) == local_name and element.text:
            return element.text.strip()
    return None


def _children_by_local_name(root: ET.Element, local_name: str) -> list[ET.Element]:
    return [element for element in root.iter() if _local_name(element.tag) == local_name]

