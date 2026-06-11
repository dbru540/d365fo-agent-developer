from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from xml.etree import ElementTree as ET


def inventory_packageslocal(packages_root: str | Path) -> dict[str, object]:
    packages_root = Path(packages_root)
    artifact_counts: Counter[str] = Counter()
    packages: list[dict[str, object]] = []

    for package_dir in _package_dirs(packages_root):
        descriptor_files = sorted((package_dir / "Descriptor").glob("*.xml")) if (package_dir / "Descriptor").exists() else []
        package_name = _descriptor_name(descriptor_files[0]) if descriptor_files else package_dir.name

        package_artifacts: list[dict[str, str]] = []
        for xml_path in sorted(package_dir.rglob("*.xml")):
            if "Descriptor" in xml_path.parts:
                continue
            artifact_type = xml_path.parent.name
            artifact_name = _artifact_name(xml_path)
            artifact_counts[artifact_type] += 1
            package_artifacts.append(
                {
                    "artifact_type": artifact_type,
                    "name": artifact_name,
                    "relative_path": str(xml_path.relative_to(packages_root)).replace("\\", "/"),
                    "details": _artifact_details(xml_path, artifact_type),
                }
            )

        packages.append(
            {
                "package_dir": package_dir.name,
                "package_name": package_name,
                "artifact_count": len(package_artifacts),
                "artifacts": package_artifacts,
            }
        )

    return {
        "packages_root": str(packages_root),
        "package_count": len(packages),
        "artifact_counts": dict(sorted(artifact_counts.items())),
        "packages": packages,
    }


def _package_dirs(packages_root: Path) -> list[Path]:
    if (packages_root / "Descriptor").exists():
        return [packages_root]
    return sorted(path for path in packages_root.iterdir() if path.is_dir())


def export_packageslocal_to_graphify(packages_root: str | Path, output_dir: str | Path) -> dict[str, object]:
    inventory = inventory_packageslocal(packages_root)
    output_dir = Path(output_dir).resolve()
    raw_packages_dir = output_dir / "raw" / "packages"
    raw_artifacts_dir = output_dir / "raw" / "artifacts"
    raw_packages_dir.mkdir(parents=True, exist_ok=True)
    raw_artifacts_dir.mkdir(parents=True, exist_ok=True)

    package_docs = 0
    artifact_docs = 0

    for package in inventory["packages"]:
        package_name = package["package_name"]
        package_doc = _render_package_doc(package)
        (raw_packages_dir / f"{package_name}.md").write_text(package_doc, encoding="utf-8")
        package_docs += 1

        for artifact in package["artifacts"]:
            artifact_doc = _render_artifact_doc(package_name, artifact)
            filename = f"{package_name}__{artifact['artifact_type']}__{artifact['name']}.md"
            (raw_artifacts_dir / filename).write_text(artifact_doc, encoding="utf-8")
            artifact_docs += 1

    manifest = {
        "packages_root": inventory["packages_root"],
        "package_count": inventory["package_count"],
        "artifact_counts": inventory["artifact_counts"],
        "package_docs": package_docs,
        "artifact_docs": artifact_docs,
    }
    (output_dir / "graphify-staging-manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    (output_dir / "graphify-staging-inventory.json").write_text(json.dumps(inventory, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest


def _descriptor_name(path: Path) -> str:
    try:
        root = ET.fromstring(path.read_text(encoding="utf-8"))
        for element in root.iter():
            if element.tag.rsplit("}", 1)[-1] == "Name" and element.text:
                return element.text.strip()
    except Exception:
        pass
    return path.stem


def _artifact_name(path: Path) -> str:
    try:
        root = ET.fromstring(path.read_text(encoding="utf-8"))
        for element in root.iter():
            if element.tag.rsplit("}", 1)[-1] == "Name" and element.text:
                return element.text.strip()
    except Exception:
        pass
    return path.stem


def _render_package_doc(package: dict[str, object]) -> str:
    artifacts = package["artifacts"]
    artifact_lines = "\n".join(
        f"- `{artifact['artifact_type']}` `{artifact['name']}` ({artifact['relative_path']})"
        for artifact in artifacts[:200]
    )
    if len(artifacts) > 200:
        artifact_lines += f"\n- ... and {len(artifacts) - 200} more artifacts"
    return (
        f"# Package {package['package_name']}\n\n"
        f"- Package Directory: `{package['package_dir']}`\n"
        f"- Artifact Count: `{package['artifact_count']}`\n\n"
        "## Artifacts\n"
        f"{artifact_lines}\n"
    )


def _render_artifact_doc(package_name: str, artifact: dict[str, str]) -> str:
    details = artifact.get("details", {})
    detail_lines = []
    if details.get("class"):
        detail_lines.append(f"- Class: `{details['class']}`")
    if details.get("auto_deploy"):
        detail_lines.append(f"- AutoDeploy: `{details['auto_deploy']}`")
    if details.get("operations"):
        detail_lines.append("## Operations")
        detail_lines.extend(f"- `{operation['name']}` -> `{operation['method']}`" for operation in details["operations"])
    if details.get("services"):
        detail_lines.append("## Services")
        detail_lines.extend(f"- `{service}`" for service in details["services"])
    extra = ("\n" + "\n".join(detail_lines) + "\n") if detail_lines else "\n"
    return (
        f"# {artifact['name']}\n\n"
        f"- Package: `{package_name}`\n"
        f"- Artifact Type: `{artifact['artifact_type']}`\n"
        f"- Relative Path: `{artifact['relative_path']}`\n"
        f"{extra}"
    )


def _artifact_details(path: Path, artifact_type: str) -> dict[str, object]:
    try:
        root = ET.fromstring(path.read_text(encoding="utf-8"))
    except Exception:
        return {}

    if artifact_type == "AxService":
        operations = []
        for operation in root.iter():
            if operation.tag.rsplit("}", 1)[-1] != "AxServiceOperation":
                continue
            operations.append(
                {
                    "name": _find_text(operation, "Name"),
                    "method": _find_text(operation, "Method"),
                }
            )
        return {
            "class": _find_text(root, "Class"),
            "operations": [item for item in operations if item["name"]],
        }

    if artifact_type == "AxServiceGroup":
        services = []
        for service in root.iter():
            if service.tag.rsplit("}", 1)[-1] not in {"AxServiceGroupService", "AxServiceReference"}:
                continue
            service_name = _find_text(service, "Service") or _find_text(service, "Name")
            if service_name:
                services.append(service_name)
        return {
            "auto_deploy": _find_text(root, "AutoDeploy"),
            "services": services,
        }

    if artifact_type in {"AxMenuItemDisplay", "AxMenuItemAction", "AxMenuItemOutput"}:
        return {
            "object": _find_text(root, "Object"),
            "object_type": _find_text(root, "ObjectType"),
            "linked_permission_object": _find_text(root, "LinkedPermissionObject"),
            "linked_permission_object_child": _find_text(root, "LinkedPermissionObjectChild"),
            "linked_permission_type": _find_text(root, "LinkedPermissionType"),
        }

    if artifact_type == "AxSecurityPrivilege":
        entry_points = []
        for entry in root.iter():
            if entry.tag.rsplit("}", 1)[-1] != "AxSecurityEntryPointReference":
                continue
            entry_points.append(
                {
                    "object_name": _find_text(entry, "ObjectName"),
                    "object_type": _find_text(entry, "ObjectType"),
                    "object_child_name": _find_text(entry, "ObjectChildName"),
                }
            )
        return {"entry_points": [item for item in entry_points if item["object_name"]]}

    if artifact_type == "AxQuery":
        root_data_source = None
        root_table = None
        for node in root.iter():
            if node.tag.rsplit("}", 1)[-1] == "AxQuerySimpleRootDataSource":
                root_data_source = _find_text(node, "Name")
                root_table = _find_text(node, "Table")
                break
        return {
            "root_data_source": root_data_source,
            "root_table": root_table,
            "allow_cross_company": _find_text(root, "AllowCrossCompany"),
        }

    if artifact_type == "AxTableExtension":
        base_name = _find_text(root, "Name")
        return {"base_table": base_name.split(".", 1)[0] if base_name and "." in base_name else None}

    if artifact_type == "AxFormExtension":
        base_name = _find_text(root, "Name")
        return {"base_form": base_name.split(".", 1)[0] if base_name and "." in base_name else None}

    if artifact_type == "AxDataEntityView":
        root_table = None
        for node in root.iter():
            if node.tag.rsplit("}", 1)[-1] == "AxQuerySimpleRootDataSource":
                root_table = _find_text(node, "Table")
                if root_table:
                    break
        return {
            "public_entity_name": _find_text(root, "PublicEntityName"),
            "root_table": root_table,
        }

    return {}


def _find_text(root: ET.Element, local_name: str) -> str | None:
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1] == local_name and element.text:
            return element.text.strip()
    return None
