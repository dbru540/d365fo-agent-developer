from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path


STOPWORDS = {
    "a",
    "an",
    "and",
    "as",
    "be",
    "by",
    "for",
    "from",
    "in",
    "is",
    "of",
    "on",
    "or",
    "the",
    "to",
    "with",
}


KEY_ALIASES = {
    "artifact id": "artifact_id",
    "artifact family": "artifact_family",
    "artifact name": "artifact_name",
    "allow cross company": "allow_cross_company",
    "root data source": "root_data_source",
    "root table": "root_table",
    "order by": "order_by",
    "service class": "service_class",
    "auto deploy": "auto_deploy",
    "label": "label",
    "configuration key": "configuration_key",
    "linked permission object": "linked_permission_object",
    "linked permission object child": "linked_permission_object_child",
    "linked permission type": "linked_permission_type",
    "model": "model",
    "package": "package",
    "target object": "target_object",
    "target kind": "target_kind",
    "public entity name": "public_entity_name",
    "public collection name": "public_collection_name",
    "edt type": "edt_subtype",
    "string size": "string_size",
    "extends": "extends",
    "reference table": "reference_table",
    "is extensible": "is_extensible",
}


@dataclass(slots=True)
class ArtifactSpec:
    title: str
    metadata: dict[str, str]
    sections: dict[str, list[str]]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class Specification:
    title: str
    raw_text: str
    metadata: dict[str, str]
    sections: dict[str, list[str]]
    artifact_specs: list[ArtifactSpec] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class ArtifactPlan:
    artifact_id: str | None
    family: str
    artifact_type: str
    model: str
    package: str
    target_object: str
    target_kind: str
    artifact_name: str
    output_path: str
    label: str | None = None
    configuration_key: str | None = None
    linked_permission_object: str | None = None
    linked_permission_object_child: str | None = None
    linked_permission_type: str | None = None
    allow_cross_company: str | None = None
    root_data_source: str | None = None
    root_table: str | None = None
    order_by: str | None = None
    service_class: str | None = None
    auto_deploy: str | None = None
    fields: list[dict[str, str]] = field(default_factory=list)
    methods: list[dict[str, str]] = field(default_factory=list)
    operations: list[dict[str, str]] = field(default_factory=list)
    controls: list[dict[str, str]] = field(default_factory=list)
    entry_points: list[dict[str, str]] = field(default_factory=list)
    services: list[dict[str, str]] = field(default_factory=list)
    privileges: list[dict[str, str]] = field(default_factory=list)
    duties: list[dict[str, str]] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    public_entity_name: str | None = None
    public_collection_name: str | None = None
    enum_values: list[dict[str, str]] = field(default_factory=list)
    mapped_fields: list[dict[str, str]] = field(default_factory=list)
    edt_subtype: str | None = None
    string_size: str | None = None
    extends: str | None = None
    reference_table: str | None = None
    is_extensible: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def load_spec(path: str | Path) -> Specification:
    path = Path(path)
    return parse_spec_text(path.read_text(encoding="utf-8"))


def parse_spec_text(text: str) -> Specification:
    lines = text.splitlines()
    title = ""
    metadata: dict[str, str] = {}
    sections: dict[str, list[str]] = {}
    artifact_specs: list[ArtifactSpec] = []
    current_section: str | None = None
    current_artifact: ArtifactSpec | None = None
    current_artifact_section: str | None = None

    for raw_line in lines:
        stripped = raw_line.strip()
        if not stripped:
            continue

        if stripped.startswith("# ") and not title:
            title = stripped[2:].strip()
            current_section = None
            current_artifact = None
            current_artifact_section = None
            continue

        if stripped.startswith("## "):
            heading = stripped[3:].strip()
            if heading.lower().startswith("artifact"):
                if current_artifact:
                    artifact_specs.append(current_artifact)
                current_artifact = ArtifactSpec(title=heading, metadata={}, sections={})
                current_artifact_section = None
                current_section = None
                continue

            if current_artifact:
                artifact_specs.append(current_artifact)
                current_artifact = None
                current_artifact_section = None

            current_section = _normalize_heading(heading)
            sections.setdefault(current_section, [])
            continue

        if stripped.startswith("### "):
            if current_artifact:
                current_artifact_section = _normalize_heading(stripped[4:].strip())
                current_artifact.sections.setdefault(current_artifact_section, [])
            else:
                current_section = _normalize_heading(stripped[4:].strip())
                sections.setdefault(current_section, [])
            continue

        if ":" in stripped and not stripped.startswith("-") and not stripped.startswith("*"):
            key, value = stripped.split(":", 1)
            alias = KEY_ALIASES.get(key.strip().lower())
            if alias:
                if current_artifact:
                    current_artifact.metadata[alias] = value.strip()
                else:
                    metadata[alias] = value.strip()
                continue

        item = stripped[2:].strip() if stripped.startswith(("- ", "* ")) else stripped
        if current_artifact and current_artifact_section:
            current_artifact.sections.setdefault(current_artifact_section, []).append(item)
        elif current_section:
            sections.setdefault(current_section, []).append(item)

    if current_artifact:
        artifact_specs.append(current_artifact)

    if not title:
        title = "Untitled Specification"

    return Specification(
        title=title,
        raw_text=text,
        metadata=metadata,
        sections=sections,
        artifact_specs=artifact_specs,
    )


def build_artifact_plan(spec: Specification) -> ArtifactPlan:
    if spec.artifact_specs:
        if len(spec.artifact_specs) != 1:
            raise ValueError("Specification contains multiple artifact blocks. Use build_artifact_plans().")
        return build_artifact_plans(spec)[0]
    return _build_artifact_plan_from_parts(spec.title, spec.metadata, spec.sections)


def build_artifact_plans(spec: Specification) -> list[ArtifactPlan]:
    if spec.artifact_specs:
        plans = [
            _build_artifact_plan_from_parts(spec.title, artifact_spec.metadata, artifact_spec.sections)
            for artifact_spec in spec.artifact_specs
        ]
        _resolve_patch_set_references(plans)
        return plans
    return [build_artifact_plan(spec)]


def infer_artifact_family(spec: Specification | ArtifactSpec) -> str | None:
    haystack = " ".join(
        [
            spec.title,
            spec.metadata.get("target_object", ""),
            " ".join(spec.sections.get("summary", [])),
            " ".join(spec.sections.get("acceptance_criteria", [])),
        ]
    ).lower()
    if "data entity" in haystack or "odata" in haystack or "public entity" in haystack:
        return "data-entity"
    if "security" in haystack or "privilege" in haystack or "menu item" in haystack:
        return "security-privilege"
    if "table extension" in haystack or "field" in haystack:
        return "table-extension"
    if "extension" in haystack or "chain of command" in haystack or "coc" in haystack:
        return "class-extension"
    return None


def extract_keywords(spec: Specification | ArtifactSpec) -> list[str]:
    text = " ".join(
        [
            spec.title,
            spec.metadata.get("target_object", ""),
            spec.metadata.get("artifact_name", ""),
            " ".join(spec.sections.get("summary", [])),
            " ".join(spec.sections.get("fields", [])),
            " ".join(spec.sections.get("methods", [])),
            " ".join(spec.sections.get("operations", [])),
            " ".join(spec.sections.get("controls", [])),
            " ".join(spec.sections.get("entry_points", [])),
            " ".join(spec.sections.get("services", [])),
            " ".join(spec.sections.get("privileges", [])),
            " ".join(spec.sections.get("duties", [])),
        ]
    )
    words = re.findall(r"[A-Za-z][A-Za-z0-9_]+", text)
    unique_words: list[str] = []
    seen: set[str] = set()
    for word in words:
        lowered = word.lower()
        if lowered in STOPWORDS or len(lowered) < 3 or lowered in seen:
            continue
        seen.add(lowered)
        unique_words.append(word)
    return unique_words


def _build_artifact_plan_from_parts(title: str, metadata: dict[str, str], sections: dict[str, list[str]]) -> ArtifactPlan:
    spec_like = ArtifactSpec(title=title, metadata=metadata, sections=sections)
    family = metadata.get("artifact_family") or infer_artifact_family(spec_like)
    if not family:
        raise ValueError("Specification does not declare or imply a supported artifact family.")

    model = metadata.get("model")
    if not model:
        raise ValueError("Specification is missing 'Model'.")
    package = metadata.get("package", model)
    target_object = metadata.get("target_object", "")
    target_kind = metadata.get("target_kind", "table").lower()

    fields = _parse_fields(sections.get("fields", []))
    enum_values = _parse_enum_values(sections.get("values", []))
    mapped_fields = (
        _parse_mapped_fields(sections.get("fields", []))
        if family in {"data-entity-view-extension", "view", "form"} else []
    )
    methods = _parse_methods(sections.get("methods", []))
    operations = _parse_operations(sections.get("operations", []))
    controls = _parse_controls(sections.get("controls", []))
    entry_points = _parse_entry_points(sections.get("entry_points", []))
    services = _parse_name_references(sections.get("services", []))
    privileges = _parse_name_references(sections.get("privileges", []))
    duties = _parse_name_references(sections.get("duties", []))
    public_entity_name = metadata.get("public_entity_name")
    public_collection_name = metadata.get("public_collection_name")

    artifact_type, artifact_name = _resolve_artifact_identity(
        family=family,
        package=package,
        target_object=target_object,
        explicit_name=metadata.get("artifact_name"),
        spec=spec_like,
    )
    output_path = _build_output_path(model, package, artifact_type, artifact_name)

    return ArtifactPlan(
        artifact_id=metadata.get("artifact_id"),
        family=family,
        artifact_type=artifact_type,
        model=model,
        package=package,
        target_object=target_object,
        target_kind=target_kind,
        artifact_name=artifact_name,
        output_path=output_path,
        label=metadata.get("label"),
        configuration_key=metadata.get("configuration_key"),
        linked_permission_object=metadata.get("linked_permission_object"),
        linked_permission_object_child=metadata.get("linked_permission_object_child"),
        linked_permission_type=metadata.get("linked_permission_type"),
        allow_cross_company=metadata.get("allow_cross_company"),
        root_data_source=metadata.get("root_data_source"),
        root_table=metadata.get("root_table"),
        order_by=metadata.get("order_by"),
        service_class=metadata.get("service_class"),
        auto_deploy=metadata.get("auto_deploy"),
        fields=fields,
        methods=methods,
        operations=operations,
        controls=controls,
        entry_points=entry_points,
        services=services,
        privileges=privileges,
        duties=duties,
        public_entity_name=public_entity_name,
        public_collection_name=public_collection_name,
        enum_values=enum_values,
        mapped_fields=mapped_fields,
        edt_subtype=metadata.get("edt_subtype"),
        string_size=metadata.get("string_size"),
        extends=metadata.get("extends"),
        reference_table=metadata.get("reference_table"),
        is_extensible=metadata.get("is_extensible"),
    )


def _resolve_artifact_identity(
    *,
    family: str,
    package: str,
    target_object: str,
    explicit_name: str | None,
    spec: Specification | ArtifactSpec,
) -> tuple[str, str]:
    if family == "table-extension":
        if not target_object:
            raise ValueError("Table-extension specs require 'Target Object'.")
        return "AxTableExtension", explicit_name or f"{target_object}.{package}"
    if family == "class-extension":
        if not target_object:
            raise ValueError("Class-extension specs require 'Target Object'.")
        return "AxClass", explicit_name or f"{target_object}_Extension"
    if family == "data-entity":
        name = explicit_name or spec.metadata.get("public_entity_name")
        if not name:
            raise ValueError("Data-entity specs require 'Artifact Name' or 'Public Entity Name'.")
        return "AxDataEntityView", name
    if family == "service":
        name = explicit_name or _camelize(spec.title)
        return "AxService", name
    if family == "form-extension":
        if not target_object:
            raise ValueError("Form-extension specs require 'Target Object'.")
        return "AxFormExtension", explicit_name or f"{target_object}.{package}"
    if family == "menu-item-action":
        name = explicit_name or _camelize(spec.title)
        return "AxMenuItemAction", name
    if family == "menu-item-display":
        name = explicit_name or _camelize(spec.title)
        return "AxMenuItemDisplay", name
    if family == "menu-item-output":
        name = explicit_name or _camelize(spec.title)
        return "AxMenuItemOutput", name
    if family == "query":
        name = explicit_name or _camelize(spec.title)
        return "AxQuery", name
    if family == "service-group":
        name = explicit_name or _camelize(spec.title)
        return "AxServiceGroup", name
    if family == "security-privilege":
        name = explicit_name or _camelize(spec.title)
        return "AxSecurityPrivilege", name
    if family == "security-duty-extension":
        if not target_object:
            raise ValueError("Security-duty-extension specs require 'Target Object'.")
        return "AxSecurityDutyExtension", explicit_name or f"{target_object}.{package}"
    if family == "security-role-extension":
        if not target_object:
            raise ValueError("Security-role-extension specs require 'Target Object'.")
        return "AxSecurityRoleExtension", explicit_name or f"{target_object}.{package}"
    if family == "enum":
        return "AxEnum", explicit_name or _camelize(spec.title)
    if family == "enum-extension":
        if not target_object:
            raise ValueError("Enum-extension specs require 'Target Object' (the base enum).")
        return "AxEnumExtension", explicit_name or f"{target_object}.{package}"
    if family == "edt":
        return "AxEdt", explicit_name or _camelize(spec.title)
    if family == "data-entity-view-extension":
        if not target_object:
            raise ValueError("Data-entity-view-extension specs require 'Target Object' (the base entity).")
        return "AxDataEntityViewExtension", explicit_name or f"{target_object}.{package}"
    if family == "view":
        return "AxView", explicit_name or _camelize(spec.title)
    if family == "class":
        return "AxClass", explicit_name or _camelize(spec.title)
    if family == "table":
        return "AxTable", explicit_name or _camelize(spec.title)
    if family == "form":
        return "AxForm", explicit_name or _camelize(spec.title)
    raise ValueError(f"Unsupported artifact family: {family}")


def _build_output_path(model: str, package: str, artifact_type: str, artifact_name: str) -> str:
    return f"src/xplusplus/models/{model}/{package}/{artifact_type}/{artifact_name}.xml"


def _parse_fields(lines: list[str]) -> list[dict[str, str]]:
    fields: list[dict[str, str]] = []
    for line in lines:
        if ":" not in line:
            continue
        name, edt = line.split(":", 1)
        fields.append({"name": name.strip(), "extended_data_type": edt.strip()})
    return fields


def _parse_enum_values(lines: list[str]) -> list[dict[str, str]]:
    """Enum value lines: ``Name`` or ``Name: @Labels:Id`` (label optional)."""
    values: list[dict[str, str]] = []
    for line in lines:
        if not line.strip():
            continue
        if ":" in line:
            name, label = line.split(":", 1)
            value = {"name": name.strip()}
            if label.strip():
                value["label"] = label.strip()
            values.append(value)
        else:
            values.append({"name": line.strip()})
    return values


def _parse_mapped_fields(lines: list[str]) -> list[dict[str, str]]:
    """Mapped-field lines for entity/view extensions: ``FieldName: DataSource.DataField`` (the
    datasource is optional: ``FieldName: DataField`` leaves it blank for the caller to default)."""
    fields: list[dict[str, str]] = []
    for line in lines:
        if ":" not in line:
            continue
        name, rhs = line.split(":", 1)
        rhs = rhs.strip()
        if "." in rhs:
            data_source, data_field = rhs.split(".", 1)
        else:
            data_source, data_field = "", rhs
        fields.append({"name": name.strip(), "data_source": data_source.strip(), "data_field": data_field.strip()})
    return fields


def _parse_methods(lines: list[str]) -> list[dict[str, str]]:
    methods: list[dict[str, str]] = []
    for line in lines:
        if ":" in line:
            signature, descriptor = line.split(":", 1)
            method_name = signature.split("(", 1)[0].strip()
            descriptor_parts = descriptor.strip().split()
            # descriptor is "<qualifiers...> <return_type>", e.g. "public static boolean".
            if not descriptor_parts:
                qualifiers, return_type = "public", "void"
            elif len(descriptor_parts) == 1:
                qualifiers, return_type = "public", descriptor_parts[0]
            else:
                qualifiers, return_type = " ".join(descriptor_parts[:-1]), descriptor_parts[-1]
            methods.append(
                {
                    "signature": signature.strip(),
                    "name": method_name,
                    "visibility": descriptor_parts[0] if descriptor_parts else "public",
                    "qualifiers": qualifiers,
                    "return_type": return_type,
                }
            )
        else:
            methods.append({"signature": line.strip(), "name": line.strip(), "visibility": "public",
                            "qualifiers": "public", "return_type": "void"})
    return methods


def _parse_operations(lines: list[str]) -> list[dict[str, str]]:
    operations: list[dict[str, str]] = []
    for line in lines:
        if "|" in line:
            name, method = line.split("|", 1)
            operations.append({"name": name.strip(), "method": method.strip()})
        elif line.strip():
            operations.append({"name": line.strip(), "method": line.strip()})
    return operations


def _parse_controls(lines: list[str]) -> list[dict[str, str]]:
    controls: list[dict[str, str]] = []
    for line in lines:
        if ":" not in line:
            continue
        control_type, remainder = line.split(":", 1)
        parts = [part.strip() for part in remainder.split("|")]
        if len(parts) < 4:
            continue
        controls.append(
            {
                "control_type": control_type.strip(),
                "name": parts[0],
                "data_source": parts[1],
                "data_field": parts[2],
                "parent": parts[3],
            }
        )
    return controls


def _parse_entry_points(lines: list[str]) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    for line in lines:
        if ":" in line:
            object_type, object_name = line.split(":", 1)
            entries.append({"object_type": object_type.strip(), "object_name": object_name.strip()})
    return entries


def _parse_name_references(lines: list[str]) -> list[dict[str, str]]:
    references: list[dict[str, str]] = []
    for line in lines:
        if not line.strip():
            continue
        if ":" in line:
            ref_type, ref_value = line.split(":", 1)
            references.append({"type": ref_type.strip(), "name": ref_value.strip()})
        else:
            references.append({"type": "name", "name": line.strip()})
    return references


def _resolve_patch_set_references(plans: list[ArtifactPlan]) -> None:
    plans_by_id = {plan.artifact_id: plan for plan in plans if plan.artifact_id}

    for plan in plans:
        resolved_entry_points: list[dict[str, str]] = []
        dependencies: set[str] = set(plan.dependencies)
        for entry in plan.entry_points:
            if entry["object_type"].lower() == "ref":
                dependency_id = entry["object_name"]
                target_plan = plans_by_id.get(dependency_id)
                if not target_plan:
                    raise ValueError(f"Unknown artifact reference: {dependency_id}")
                resolved_entry_points.append(
                    {
                        "object_type": _artifact_type_to_security_object_type(target_plan.artifact_type),
                        "object_name": target_plan.artifact_name,
                    }
                )
                dependencies.add(dependency_id)
            else:
                resolved_entry_points.append(entry)
        plan.entry_points = resolved_entry_points

        resolved_privileges: list[dict[str, str]] = []
        for privilege in plan.privileges:
            if privilege["type"].lower() == "ref":
                dependency_id = privilege["name"]
                target_plan = plans_by_id.get(dependency_id)
                if not target_plan:
                    raise ValueError(f"Unknown artifact reference: {dependency_id}")
                resolved_privileges.append({"name": target_plan.artifact_name})
                dependencies.add(dependency_id)
            else:
                resolved_privileges.append({"name": privilege["name"]})
        plan.privileges = resolved_privileges

        resolved_services: list[dict[str, str]] = []
        for service in plan.services:
            if service["type"].lower() == "ref":
                dependency_id = service["name"]
                target_plan = plans_by_id.get(dependency_id)
                if not target_plan:
                    raise ValueError(f"Unknown artifact reference: {dependency_id}")
                resolved_services.append({"name": target_plan.artifact_name})
                dependencies.add(dependency_id)
            else:
                resolved_services.append({"name": service["name"]})
        plan.services = resolved_services

        resolved_duties: list[dict[str, str]] = []
        for duty in plan.duties:
            if duty["type"].lower() == "ref":
                dependency_id = duty["name"]
                target_plan = plans_by_id.get(dependency_id)
                if not target_plan:
                    raise ValueError(f"Unknown artifact reference: {dependency_id}")
                resolved_duties.append({"name": _duty_reference_name(target_plan)})
                dependencies.add(dependency_id)
            else:
                resolved_duties.append({"name": duty["name"]})
        plan.duties = resolved_duties
        plan.dependencies = sorted(dependencies)


def _artifact_type_to_security_object_type(artifact_type: str) -> str:
    mapping = {
        "AxMenuItemDisplay": "MenuItemDisplay",
        "AxMenuItemAction": "MenuItemAction",
        "AxMenuItemOutput": "MenuItemOutput",
        "AxForm": "DisplayTarget",
    }
    return mapping.get(artifact_type, artifact_type.replace("Ax", ""))


def _duty_reference_name(plan: ArtifactPlan) -> str:
    if plan.artifact_type == "AxSecurityDutyExtension":
        return plan.target_object
    return plan.artifact_name


def _normalize_heading(heading: str) -> str:
    return heading.strip().lower().replace(" ", "_")


def _camelize(value: str) -> str:
    parts = re.findall(r"[A-Za-z0-9]+", value)
    return "".join(part[:1].upper() + part[1:] for part in parts) or "GeneratedArtifact"
