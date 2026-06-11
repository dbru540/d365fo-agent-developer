from __future__ import annotations

import json
from pathlib import Path
from typing import Callable
from xml.etree import ElementTree as ET

from d365fo_agent.indexer import build_catalog
from d365fo_agent.graph_query import GraphIndex, discover_graph_path
from d365fo_agent.models import Artifact, Catalog
from d365fo_agent.rules import load_rules
from d365fo_agent.specs import (
    ArtifactPlan,
    ArtifactSpec,
    Specification,
    build_artifact_plans,
    extract_keywords,
    load_spec,
)

# A resolver maps an EDT name to its concrete AOT table-field type, or None if it can't (the caller
# then falls back to a heuristic). Built at the generation boundary from the index + file roots.
FieldTypeResolver = Callable[[str], "str | None"]

# Kernel/system BASE enums that have no AxEnum XML in PackagesLocalDirectory (so they never appear
# in the corpus index). A table/form field on one of these uses <EnumType>, not <ExtendedDataType>.
# Conservative on purpose — only names that are certainly base enums, so we never mis-type a field.
_KNOWN_BASE_ENUMS = {"NoYes", "Gender", "Weekday", "Timezone"}


def build_generation_bundle(
    spec: Specification | ArtifactSpec,
    plan: ArtifactPlan,
    catalog: Catalog,
    repo_root: str | Path,
    *,
    example_limit: int = 3,
    graph_index=None,
    graph_query: str | None = None,
) -> dict[str, object]:
    repo_root = Path(repo_root)
    graph_labels: set[str] = set()
    graph_materialized_examples: list[dict[str, object]] = []
    if graph_index is not None and graph_query:
        graph_labels = graph_index.related_label_set(graph_query, limit=max(example_limit * 4, 10))
        graph_materialized_examples = graph_index.materialize_related_examples(graph_query, limit=example_limit)

    candidates: list[tuple[tuple[int, int, int, int], int, str, object]] = []
    for artifact in catalog.artifacts:
        score = _artifact_score(artifact, plan, spec, graph_labels)
        candidates.append((score, 0, "catalog", artifact))
    for graph_example in graph_materialized_examples:
        score = _graph_example_score(graph_example, plan, spec)
        candidates.append((score, 1, "graph", graph_example))

    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)

    graph_names: set[str] = set()
    for graph_example in graph_materialized_examples:
        graph_name = graph_example.get("artifact", {}).get("name") if isinstance(graph_example, dict) else None
        if graph_name:
            graph_names.add(graph_name)

    examples: list[dict[str, object]] = []
    used_names: set[str] = set()
    for _, _, kind, payload_entry in candidates:
        if kind == "graph":
            name = payload_entry["artifact"]["name"]
            if not name or name in used_names:
                continue
            examples.append(payload_entry)
            used_names.add(name)
        else:
            artifact = payload_entry
            if artifact.name in used_names:
                continue
            if artifact.name in graph_names:
                continue
            path = repo_root / artifact.relative_path
            content = path.read_text(encoding="utf-8", errors="ignore")
            examples.append({"artifact": artifact.to_dict(), "content": content})
            used_names.add(artifact.name)
        if len(examples) >= example_limit:
            break

    payload = {
        "spec": spec.to_dict(),
        "artifact_plan": plan.to_dict(),
        "examples": examples,
    }
    if graph_index is not None and graph_query:
        payload["graph_examples"] = graph_index.related_nodes(graph_query, limit=example_limit)
    return payload


def _make_field_resolver(index: object, roots: list[Path]) -> FieldTypeResolver:
    """Build the EDT->field-type resolver used during generation. Reads each EDT's real base type
    from the corpus (``knowledge.resolve_edt_field_type``); returns None per EDT when unresolvable."""
    from d365fo_agent import knowledge

    def resolve(edt: str) -> str | None:
        return knowledge.resolve_edt_field_type(index, edt, roots)

    def enum_name(edt: str) -> str | None:
        # A field whose type is a BASE enum (AxEnum) carries <EnumType>, not <ExtendedDataType>.
        # Kernel/system base enums (NoYes, …) have no AxEnum XML in PackagesLocalDirectory, so they
        # are NOT in the index — recognise the well-known ones by name.
        if edt in _KNOWN_BASE_ENUMS:
            return edt
        try:
            return edt if index.exists(edt, "AxEnum") else None  # type: ignore[attr-defined]
        except Exception:
            return None

    resolve.enum_name = enum_name  # type: ignore[attr-defined]  # consumed by _render_table_field
    return resolve


def generate_from_spec_file(
    spec_path: str | Path,
    repo_root: str | Path,
    rules_path: str | Path,
    output_dir: str | Path,
    *,
    example_limit: int = 3,
    graph_path: str | Path | None = None,
    db_path: str | Path | None = None,
) -> dict[str, object]:
    spec = load_spec(spec_path)
    plans = build_artifact_plans(spec)
    catalog = build_catalog(repo_root, load_rules(rules_path))
    graph_index = None
    resolved_graph_path = Path(graph_path) if graph_path else discover_graph_path(repo_root)
    if resolved_graph_path and resolved_graph_path.exists():
        graph_index = GraphIndex(resolved_graph_path)
    # Index-backed field typing: with a db, table-extension fields get their real AOT type from the
    # corpus (AxTableFieldReal/Enum/…) — resolved by reading each EDT's i:type — instead of the
    # AxTableFieldString fallback. Optional: without a db, generation behaves exactly as before.
    index = None
    field_resolver: FieldTypeResolver | None = None
    if db_path and Path(db_path).exists():
        from d365fo_agent.index_store import D365Index

        index = D365Index(db_path)
        field_resolver = _make_field_resolver(index, [Path(repo_root), Path(repo_root) / "PackagesLocalDirectory"])

    spec_blocks = spec.artifact_specs if spec.artifact_specs else [_spec_as_artifact_block(spec)]
    artifact_bundles: list[dict[str, object]] = []
    generated_files: list[str] = []
    artifact_results: list[dict[str, object]] = []

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    for artifact_spec, plan in zip(spec_blocks, plans, strict=True):
        _redirect_plan_to_existing_extension(plan, Path(repo_root))
        graph_query = plan.artifact_name or plan.target_object or plan.service_class
        bundle = build_generation_bundle(
            artifact_spec,
            plan,
            catalog,
            repo_root,
            example_limit=example_limit,
            graph_index=graph_index,
            graph_query=graph_query,
        )
        artifact_bundles.append(bundle)

        generated_path = output_dir / plan.output_path
        generated_path.parent.mkdir(parents=True, exist_ok=True)
        source_path = Path(repo_root) / plan.output_path
        generation_mode = "created"
        xml_text = render_artifact(plan, field_resolver)
        if source_path.exists():
            xml_text = merge_artifact(plan, source_path.read_text(encoding="utf-8"), field_resolver)
            generation_mode = "merged"
        generated_path.write_text(xml_text, encoding="utf-8")
        generated_files.append(str(generated_path.relative_to(output_dir)).replace("\\", "/"))
        artifact_results.append(
            {
                "artifact_id": plan.artifact_id,
                "artifact_name": plan.artifact_name,
                "artifact_type": plan.artifact_type,
                "generated_file": str(generated_path.relative_to(output_dir)).replace("\\", "/"),
                "generation_mode": generation_mode,
                "source_exists": source_path.exists(),
            }
        )

    bundle_payload = {
        "spec": spec.to_dict(),
        "artifacts": artifact_bundles,
    }
    bundle_path = output_dir / "generation-bundle.json"
    bundle_path.write_text(json.dumps(bundle_payload, indent=2, ensure_ascii=False), encoding="utf-8")

    manifest: dict[str, object] = {
        "generated_files": generated_files,
        "artifact_results": artifact_results,
        "bundle_path": str(bundle_path.relative_to(output_dir)).replace("\\", "/"),
        "patch_set": {
            "artifact_count": len(plans),
            "artifact_ids": [plan.artifact_id for plan in plans if plan.artifact_id],
        },
    }
    if len(plans) == 1:
        manifest["artifact_plan"] = plans[0].to_dict()
    else:
        manifest["artifact_plans"] = [plan.to_dict() for plan in plans]

    manifest_path = output_dir / "generation-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    if index is not None:
        index.close()
    return manifest


def merge_artifact(plan: ArtifactPlan, existing_xml: str, resolver: FieldTypeResolver | None = None) -> str:
    if plan.family == "table-extension":
        return _merge_table_extension(plan, existing_xml, resolver)
    if plan.family == "class-extension":
        return _merge_class_extension(plan, existing_xml)
    if plan.family == "service":
        return _merge_service(plan, existing_xml)
    if plan.family == "service-group":
        return _merge_service_group(plan, existing_xml)
    if plan.family == "form-extension":
        return _merge_form_extension(plan, existing_xml)
    if plan.family == "menu-item-display":
        return _merge_menu_item(plan, existing_xml)
    if plan.family == "menu-item-action":
        return _merge_menu_item(plan, existing_xml)
    if plan.family == "menu-item-output":
        return _merge_menu_item_output(plan, existing_xml)
    if plan.family == "query":
        return _merge_query(plan, existing_xml)
    if plan.family == "security-privilege":
        return _merge_security_privilege(plan, existing_xml)
    if plan.family == "security-duty-extension":
        return _merge_security_duty_extension(plan, existing_xml)
    if plan.family == "security-role-extension":
        return _merge_security_role_extension(plan, existing_xml)
    return existing_xml


def render_artifact(plan: ArtifactPlan, resolver: FieldTypeResolver | None = None) -> str:
    if plan.family == "table-extension":
        return _render_table_extension(plan, resolver)
    if plan.family == "class-extension":
        return _render_class_extension(plan)
    if plan.family == "service":
        return _render_service(plan)
    if plan.family == "service-group":
        return _render_service_group(plan)
    if plan.family == "data-entity":
        return _render_data_entity(plan)
    if plan.family == "form-extension":
        return _render_form_extension(plan)
    if plan.family == "menu-item-action":
        return _render_menu_item_action(plan)
    if plan.family == "menu-item-display":
        return _render_menu_item_display(plan)
    if plan.family == "menu-item-output":
        return _render_menu_item_output(plan)
    if plan.family == "query":
        return _render_query(plan)
    if plan.family == "security-privilege":
        return _render_security_privilege(plan)
    if plan.family == "security-duty-extension":
        return _render_security_duty_extension(plan)
    if plan.family == "security-role-extension":
        return _render_security_role_extension(plan)
    if plan.family == "enum":
        return _render_enum(plan)
    if plan.family == "enum-extension":
        return _render_enum_extension(plan)
    if plan.family == "edt":
        return _render_edt(plan)
    if plan.family == "data-entity-view-extension":
        return _render_data_entity_view_extension(plan)
    if plan.family == "view":
        return _render_view(plan)
    if plan.family == "class":
        return _render_class(plan)
    if plan.family == "table":
        return _render_table(plan, resolver)
    if plan.family == "form":
        return _render_form(plan)
    raise ValueError(f"Unsupported artifact family: {plan.family}")


# --- deterministic generators for enum / EDT / view / their extensions -------------
# Each XML shape is grounded on a real corpus example (BABInvoiceStatus, LedgerPostingType.*,
# BABString100, BankAccountEntity.*, BABCompanyView).

_EDT_SUBTYPE_ALIASES = {
    "string": "AxEdtString", "int": "AxEdtInt", "integer": "AxEdtInt", "int64": "AxEdtInt64",
    "real": "AxEdtReal", "date": "AxEdtDate", "time": "AxEdtTime", "utcdatetime": "AxEdtUtcDateTime",
    "guid": "AxEdtGuid", "container": "AxEdtContainer", "enum": "AxEdtEnum",
}


def _enum_values_xml(values: list[dict[str, str]], *, with_index: bool) -> str:
    parts: list[str] = []
    for i, value in enumerate(values):
        lines = ["\t\t<AxEnumValue>", f"\t\t\t<Name>{value['name']}</Name>"]
        if value.get("label"):
            lines.append(f"\t\t\t<Label>{value['label']}</Label>")
        if with_index and i > 0:  # first value defaults to 0; D365 omits <Value>0</Value>
            lines.append(f"\t\t\t<Value>{i}</Value>")
        lines.append("\t\t</AxEnumValue>")
        parts.append("\n".join(lines))
    return "\n".join(parts)


def _render_enum(plan: ArtifactPlan) -> str:
    label_line = f"\t<Label>{plan.label}</Label>\n" if plan.label else ""
    values = _enum_values_xml(plan.enum_values, with_index=True)
    values_block = f"\t<EnumValues>\n{values}\n\t</EnumValues>" if values else "\t<EnumValues />"
    extensible = (plan.is_extensible or "true").strip().lower()
    extensible = "true" if extensible in {"true", "yes", "1"} else "false"
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<AxEnum xmlns:i="http://www.w3.org/2001/XMLSchema-instance">\n'
        f"\t<Name>{plan.artifact_name}</Name>\n"
        f"{label_line}"
        "\t<UseEnumValue>No</UseEnumValue>\n"
        f"{values_block}\n"
        f"\t<IsExtensible>{extensible}</IsExtensible>\n"
        "</AxEnum>\n"
    )


def _render_enum_extension(plan: ArtifactPlan) -> str:
    values = _enum_values_xml(plan.enum_values, with_index=False)  # extensions auto-assign values
    values_block = f"\t<EnumValues>\n{values}\n\t</EnumValues>" if values else "\t<EnumValues />"
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<AxEnumExtension xmlns:i="http://www.w3.org/2001/XMLSchema-instance">\n'
        f"\t<Name>{plan.artifact_name}</Name>\n"
        f"{values_block}\n"
        "\t<PropertyModifications />\n"
        "\t<ValueModifications />\n"
        "</AxEnumExtension>\n"
    )


def _render_edt(plan: ArtifactPlan) -> str:
    raw = (plan.edt_subtype or "AxEdtString").strip()
    subtype = raw if raw.startswith("AxEdt") else _EDT_SUBTYPE_ALIASES.get(raw.lower(), "AxEdtString")
    label_line = f"\t<Label>{plan.label}</Label>\n" if plan.label else ""
    extends_line = f"\t<Extends>{plan.extends}</Extends>\n" if plan.extends else ""
    ref_line = f"\t<ReferenceTable>{plan.reference_table}</ReferenceTable>\n" if plan.reference_table else ""
    # String EDTs carry a StringSize; default 10 if a string EDT omits it.
    size_line = ""
    if subtype == "AxEdtString":
        size_line = f"\t<StringSize>{plan.string_size or '10'}</StringSize>\n"
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        f'<AxEdt xmlns:i="http://www.w3.org/2001/XMLSchema-instance" xmlns="" i:type="{subtype}">\n'
        f"\t<Name>{plan.artifact_name}</Name>\n"
        f"{label_line}{extends_line}{ref_line}"
        "\t<ArrayElements />\n"
        "\t<Relations />\n"
        "\t<TableReferences />\n"
        f"{size_line}"
        "</AxEdt>\n"
    )


def _mapped_field_xml(field: dict[str, str], default_source: str, field_element: str, mapped_type: str) -> str:
    source = field.get("data_source") or default_source
    data_field = field.get("data_field") or field["name"]
    return (
        f'\t\t<{field_element} xmlns="" i:type="{mapped_type}">\n'
        f"\t\t\t<Name>{field['name']}</Name>\n"
        f"\t\t\t<DataField>{data_field}</DataField>\n"
        f"\t\t\t<DataSource>{source}</DataSource>\n"
        f"\t\t</{field_element}>"
    )


def _render_data_entity_view_extension(plan: ArtifactPlan) -> str:
    default_source = plan.root_data_source or plan.target_object
    fields = "\n".join(
        _mapped_field_xml(f, default_source, "AxDataEntityViewField", "AxDataEntityViewMappedField")
        for f in plan.mapped_fields
    )
    fields_block = f"\t<Fields>\n{fields}\n\t</Fields>" if fields else "\t<Fields />"
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<AxDataEntityViewExtension xmlns:i="http://www.w3.org/2001/XMLSchema-instance">\n'
        f"\t<Name>{plan.artifact_name}</Name>\n"
        "\t<DataSources />\n"
        "\t<FieldGroupExtensions />\n"
        "\t<FieldGroups />\n"
        "\t<FieldModifications />\n"
        f"{fields_block}\n"
        "\t<Mappings />\n"
        "\t<PropertyModifications />\n"
        "\t<Relations />\n"
        "</AxDataEntityViewExtension>\n"
    )


_VIEW_FIELD_GROUPS = (
    '\t\t<AxTableFieldGroup>\n\t\t\t<Name>AutoReport</Name>\n\t\t\t<Fields />\n\t\t</AxTableFieldGroup>\n'
    '\t\t<AxTableFieldGroup>\n\t\t\t<Name>AutoLookup</Name>\n\t\t\t<Fields />\n\t\t</AxTableFieldGroup>\n'
    '\t\t<AxTableFieldGroup>\n\t\t\t<Name>AutoIdentification</Name>\n\t\t\t<AutoPopulate>Yes</AutoPopulate>\n\t\t\t<Fields />\n\t\t</AxTableFieldGroup>\n'
    '\t\t<AxTableFieldGroup>\n\t\t\t<Name>AutoSummary</Name>\n\t\t\t<Fields />\n\t\t</AxTableFieldGroup>\n'
    '\t\t<AxTableFieldGroup>\n\t\t\t<Name>AutoBrowse</Name>\n\t\t\t<Fields />\n\t\t</AxTableFieldGroup>'
)


def _render_view(plan: ArtifactPlan) -> str:
    # Single-root-datasource view (the common case). Multi-datasource joins are better started from
    # a real example via scaffold_object; this emits a valid, compilable single-table view skeleton.
    root_source = plan.root_data_source or plan.root_table or plan.target_object or "RootDataSource"
    root_table = plan.root_table or plan.target_object or root_source
    fields = "\n".join(
        _mapped_field_xml(f, root_source, "AxViewField", "AxViewFieldBound") for f in plan.mapped_fields
    )
    fields_block = f"\t<Fields>\n{fields}\n\t</Fields>" if fields else "\t<Fields />"
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<AxView xmlns:i="http://www.w3.org/2001/XMLSchema-instance">\n'
        f"\t<Name>{plan.artifact_name}</Name>\n"
        "\t<SourceCode>\n"
        f"\t\t<Declaration><![CDATA[\npublic class {plan.artifact_name} extends common\n{{\n}}\n]]></Declaration>\n"
        "\t\t<Methods />\n"
        "\t</SourceCode>\n"
        "\t<SubscriberAccessLevel>\n\t\t<Read>Allow</Read>\n\t</SubscriberAccessLevel>\n"
        f"\t<FieldGroups>\n{_VIEW_FIELD_GROUPS}\n\t</FieldGroups>\n"
        f"{fields_block}\n"
        "\t<Indexes />\n"
        "\t<Mappings />\n"
        "\t<Relations />\n"
        "\t<StateMachines />\n"
        "\t<ViewMetadata>\n"
        "\t\t<Name>Metadata</Name>\n"
        "\t\t<SourceCode>\n\t\t\t<Methods />\n\t\t</SourceCode>\n"
        "\t\t<DataSources>\n"
        "\t\t\t<AxQuerySimpleRootDataSource>\n"
        f"\t\t\t\t<Name>{root_source}</Name>\n"
        "\t\t\t\t<DynamicFields>Yes</DynamicFields>\n"
        f"\t\t\t\t<Table>{root_table}</Table>\n"
        "\t\t\t\t<DataSources />\n"
        "\t\t\t\t<DerivedDataSources />\n"
        "\t\t\t\t<Fields />\n"
        "\t\t\t\t<Ranges />\n"
        "\t\t\t</AxQuerySimpleRootDataSource>\n"
        "\t\t</DataSources>\n"
        "\t</ViewMetadata>\n"
        "</AxView>\n"
    )


def _render_class(plan: ArtifactPlan) -> str:
    """A new standalone AxClass: declaration (optionally extending a base) + method stubs from the
    spec. The agent fills in the X++ logic in the bodies; this gives it the right structure."""
    extends = f" extends {plan.extends}" if plan.extends else ""
    methods = "\n".join(_render_method(method) for method in plan.methods)
    methods_block = f"\t\t<Methods>\n{methods}\n\t\t</Methods>" if methods else "\t\t<Methods />"
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<AxClass xmlns:i="http://www.w3.org/2001/XMLSchema-instance">\n'
        f"\t<Name>{plan.artifact_name}</Name>\n"
        "\t<SourceCode>\n"
        f"\t\t<Declaration><![CDATA[\npublic class {plan.artifact_name}{extends}\n{{\n}}\n]]></Declaration>\n"
        f"{methods_block}\n"
        "\t</SourceCode>\n"
        "</AxClass>\n"
    )


def _render_table(plan: ArtifactPlan, resolver: FieldTypeResolver | None = None) -> str:
    """A new standalone AxTable: declaration + fields (typed via the EDT resolver) + the standard
    auto field groups + empty index/relation containers. The agent adds indexes/relations/logic."""
    label_line = f"\t<Label>{plan.label}</Label>\n" if plan.label else ""
    ck_line = f"\t<ConfigurationKey>{plan.configuration_key}</ConfigurationKey>\n" if plan.configuration_key else ""
    fields = "\n".join(_render_table_field(field, resolver) for field in plan.fields)
    fields_block = f"\t<Fields>\n{fields}\n\t</Fields>" if fields else "\t<Fields />"
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<AxTable xmlns:i="http://www.w3.org/2001/XMLSchema-instance">\n'
        f"\t<Name>{plan.artifact_name}</Name>\n"
        "\t<SourceCode>\n"
        f"\t\t<Declaration><![CDATA[\npublic class {plan.artifact_name} extends common\n{{\n}}\n]]></Declaration>\n"
        "\t\t<Methods />\n"
        "\t</SourceCode>\n"
        f"{label_line}{ck_line}"
        "\t<DeleteActions />\n"
        f"\t<FieldGroups>\n{_VIEW_FIELD_GROUPS}\n\t</FieldGroups>\n"
        f"{fields_block}\n"
        "\t<FullTextIndexes />\n"
        "\t<Indexes />\n"
        "\t<Mappings />\n"
        "\t<Relations />\n"
        "\t<StateMachines />\n"
        "</AxTable>\n"
    )


# The SimpleList form pattern requires an ActionPane, a CustomFilterGroup (with a QuickFilter), and
# a Grid. This is the CustomFilterGroup, grounded on a real corpus form.
_FORM_CUSTOM_FILTER_GROUP = (
    '\t\t\t<AxFormControl xmlns="" i:type="AxFormGroupControl">\n'
    "\t\t\t\t<Name>CustomFilterGroup</Name>\n"
    "\t\t\t\t<Pattern>CustomAndQuickFilters</Pattern>\n"
    "\t\t\t\t<PatternVersion>1.1</PatternVersion>\n"
    "\t\t\t\t<Type>Group</Type>\n"
    "\t\t\t\t<WidthMode>SizeToAvailable</WidthMode>\n"
    '\t\t\t\t<FormControlExtension i:nil="true" />\n'
    "\t\t\t\t<Controls>\n"
    "\t\t\t\t\t<AxFormControl>\n"
    "\t\t\t\t\t\t<Name>QuickFilter</Name>\n"
    "\t\t\t\t\t\t<FormControlExtension>\n"
    "\t\t\t\t\t\t\t<Name>QuickFilterControl</Name>\n"
    "\t\t\t\t\t\t\t<ExtensionComponents />\n"
    "\t\t\t\t\t\t\t<ExtensionProperties>\n"
    "\t\t\t\t\t\t\t\t<AxFormControlExtensionProperty>\n"
    "\t\t\t\t\t\t\t\t\t<Name>targetControlName</Name>\n\t\t\t\t\t\t\t\t\t<Type>String</Type>\n"
    "\t\t\t\t\t\t\t\t</AxFormControlExtensionProperty>\n"
    "\t\t\t\t\t\t\t</ExtensionProperties>\n"
    "\t\t\t\t\t\t</FormControlExtension>\n"
    "\t\t\t\t\t</AxFormControl>\n"
    "\t\t\t\t</Controls>\n"
    "\t\t\t\t<ArrangeMethod>HorizontalLeft</ArrangeMethod>\n"
    "\t\t\t\t<FrameType>None</FrameType>\n"
    "\t\t\t\t<Style>CustomFilter</Style>\n"
    "\t\t\t\t<ViewEditMode>Edit</ViewEditMode>\n"
    "\t\t\t</AxFormControl>"
)


def _render_form(plan: ArtifactPlan) -> str:
    """A minimal but valid SimpleList AxForm bound to one datasource, with a grid of the requested
    columns. A starting point the agent fleshes out (more controls, patterns); richer forms are
    better started from a real example via scaffold_object."""
    table = plan.root_table or plan.target_object or "RootTable"
    ds = plan.root_data_source or table
    caption = plan.label or f"@{plan.artifact_name}"
    columns = plan.mapped_fields or [{"name": f["name"], "data_field": f["name"]} for f in plan.fields]

    def _datafield(col: dict[str, str]) -> str:
        return col.get("data_field") or col["name"]

    ds_fields = "\n".join(
        f"\t\t\t\t<AxFormDataSourceField>\n\t\t\t\t\t<DataField>{_datafield(c)}</DataField>\n\t\t\t\t</AxFormDataSourceField>"
        for c in columns
    )
    ds_fields_block = f"\t\t\t<Fields>\n{ds_fields}\n\t\t\t</Fields>" if ds_fields else "\t\t\t<Fields />"
    grid_controls = "\n".join(
        '\t\t\t\t<AxFormControl xmlns="" i:type="AxFormStringControl">\n'
        f"\t\t\t\t\t<Name>Grid_{c['name']}</Name>\n"
        "\t\t\t\t\t<Type>String</Type>\n"
        '\t\t\t\t\t<FormControlExtension i:nil="true" />\n'
        f"\t\t\t\t\t<DataField>{_datafield(c)}</DataField>\n"
        f"\t\t\t\t\t<DataSource>{ds}</DataSource>\n"
        "\t\t\t\t</AxFormControl>"
        for c in columns
    )
    grid_inner = f"\t\t\t\t<Controls>\n{grid_controls}\n\t\t\t\t</Controls>" if grid_controls else "\t\t\t\t<Controls />"
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<AxForm xmlns:i="http://www.w3.org/2001/XMLSchema-instance" xmlns="Microsoft.Dynamics.AX.Metadata.V6">\n'
        f"\t<Name>{plan.artifact_name}</Name>\n"
        "\t<SourceCode>\n"
        '\t\t<Methods xmlns="">\n\t\t\t<Method>\n\t\t\t\t<Name>classDeclaration</Name>\n'
        f"\t\t\t\t<Source><![CDATA[\n[Form]\npublic class {plan.artifact_name} extends FormRun\n{{\n}}\n]]></Source>\n"
        "\t\t\t</Method>\n\t\t</Methods>\n"
        '\t\t<DataSources xmlns="" />\n\t\t<DataControls xmlns="" />\n\t\t<Members xmlns="" />\n'
        "\t</SourceCode>\n"
        "\t<DataSources>\n"
        f'\t\t<AxFormDataSource xmlns="">\n\t\t\t<Name>{ds}</Name>\n\t\t\t<Table>{table}</Table>\n'
        f"{ds_fields_block}\n"
        "\t\t\t<ReferencedDataSources />\n\t\t\t<InsertAtEnd>No</InsertAtEnd>\n\t\t\t<InsertIfEmpty>No</InsertIfEmpty>\n"
        "\t\t\t<DataSourceLinks />\n\t\t\t<DerivedDataSources />\n\t\t</AxFormDataSource>\n"
        "\t</DataSources>\n"
        "\t<Design>\n"
        f'\t\t<Caption xmlns="">{caption}</Caption>\n'
        '\t\t<Pattern xmlns="">SimpleList</Pattern>\n\t\t<PatternVersion xmlns="">1.1</PatternVersion>\n\t\t<Style xmlns="">SimpleList</Style>\n'
        '\t\t<Controls xmlns="">\n'
        '\t\t\t<AxFormControl xmlns="" i:type="AxFormActionPaneControl">\n'
        "\t\t\t\t<Name>ActionPane</Name>\n\t\t\t\t<Type>ActionPane</Type>\n"
        '\t\t\t\t<FormControlExtension i:nil="true" />\n\t\t\t\t<Controls />\n'
        "\t\t\t</AxFormControl>\n"
        f"{_FORM_CUSTOM_FILTER_GROUP}\n"
        '\t\t\t<AxFormControl xmlns="" i:type="AxFormGridControl">\n'
        '\t\t\t\t<Name>Grid</Name>\n\t\t\t\t<Type>Grid</Type>\n\t\t\t\t<FormControlExtension i:nil="true" />\n'
        f"{grid_inner}\n"
        f"\t\t\t\t<DataGroup>AutoBrowse</DataGroup>\n\t\t\t\t<DataSource>{ds}</DataSource>\n\t\t\t\t<Style>Tabular</Style>\n"
        "\t\t\t</AxFormControl>\n"
        "\t\t</Controls>\n"
        "\t</Design>\n"
        "\t<Parts />\n"
        "</AxForm>\n"
    )


def _artifact_score(
    artifact: Artifact,
    plan: ArtifactPlan,
    spec: Specification | ArtifactSpec,
    graph_labels: set[str] | None = None,
) -> tuple[int, int, int, int]:
    keywords = {keyword.lower() for keyword in extract_keywords(spec)}
    haystack = " ".join([artifact.name, artifact.relative_path, artifact.label or ""]).lower()
    overlap = sum(1 for keyword in keywords if keyword in haystack)
    exact_name = int(artifact.name == plan.artifact_name or artifact.name == plan.target_object)
    same_type = int(artifact.artifact_type == plan.artifact_type)
    same_model = int(artifact.model == plan.model)
    graph_boost = 0
    if graph_labels and artifact.name in graph_labels:
        graph_boost = 12
    return same_type * 10 + exact_name * 8 + same_model * 5 + overlap + graph_boost, graph_boost, exact_name, overlap


def _graph_example_score(
    graph_example: dict[str, object],
    plan: ArtifactPlan,
    spec: Specification | ArtifactSpec,
) -> tuple[int, int, int, int]:
    artifact_info = graph_example.get("artifact", {}) if isinstance(graph_example, dict) else {}
    name = artifact_info.get("name") or ""
    artifact_type = artifact_info.get("artifact_type") or ""
    relative_path = artifact_info.get("relative_path") or ""
    keywords = {keyword.lower() for keyword in extract_keywords(spec)}
    haystack = " ".join([name, relative_path, artifact_type]).lower()
    overlap = sum(1 for keyword in keywords if keyword in haystack)
    exact_name = int(name == plan.artifact_name or name == plan.target_object)
    same_type = int(artifact_type == plan.artifact_type)
    graph_boost = 12
    return same_type * 10 + exact_name * 8 + overlap + graph_boost, graph_boost, exact_name, overlap


def _spec_as_artifact_block(spec: Specification) -> ArtifactSpec:
    return ArtifactSpec(title=spec.title, metadata=spec.metadata, sections=spec.sections)


def _redirect_plan_to_existing_extension(plan: ArtifactPlan, repo_root: Path) -> None:
    if plan.family != "table-extension" or not plan.target_object:
        return
    candidate_source = repo_root / plan.output_path
    if candidate_source.exists():
        return
    parent_dir = candidate_source.parent
    if not parent_dir.exists():
        return
    alternatives = [
        path
        for path in parent_dir.glob(f"{plan.target_object}.*.xml")
        if path != candidate_source
    ]
    if len(alternatives) != 1:
        return
    alt_path = alternatives[0]
    try:
        rel_path = alt_path.relative_to(repo_root)
    except ValueError:
        return
    plan.output_path = str(rel_path).replace("\\", "/")
    plan.artifact_name = alt_path.stem


def _render_table_extension(plan: ArtifactPlan, resolver: FieldTypeResolver | None = None) -> str:
    fields = "\n".join(_render_table_field(field, resolver) for field in plan.fields) or "    <Fields />"
    return f"""<?xml version="1.0" encoding="utf-8"?>
<AxTableExtension xmlns:i="http://www.w3.org/2001/XMLSchema-instance">
\t<Name>{plan.artifact_name}</Name>
\t<FieldGroupExtensions />
\t<FieldGroups />
\t<FieldModifications />
\t<Fields>
{fields}
\t</Fields>
\t<FullTextIndexes />
\t<Indexes />
\t<Mappings />
\t<PropertyModifications />
\t<RelationExtensions />
\t<RelationModifications />
\t<Relations />
</AxTableExtension>
"""


def _render_table_field(field: dict[str, str], resolver: FieldTypeResolver | None = None) -> str:
    edt = field["extended_data_type"]
    enum_fn = getattr(resolver, "enum_name", None)
    enum = enum_fn(edt) if enum_fn else None
    if enum:  # a base-enum field carries <EnumType>, not <ExtendedDataType>
        field_type, inner = "AxTableFieldEnum", f"\t\t\t<EnumType>{enum}</EnumType>"
    else:
        field_type = _table_field_type_for_edt(edt, resolver)
        inner = f"\t\t\t<ExtendedDataType>{edt}</ExtendedDataType>"
    return (
        f'\t\t<AxTableField xmlns="" i:type="{field_type}">\n'
        f"\t\t\t<Name>{field['name']}</Name>\n"
        f"{inner}\n"
        "\t\t</AxTableField>"
    )


def _table_field_type_for_edt(edt: str, resolver: FieldTypeResolver | None = None) -> str:
    """Resolve the concrete AOT field type (``AxTableFieldReal``/``…Enum``/``…Int64``/…) for an EDT.

    Prefer the resolver (the EDT's real base type from the corpus — see
    ``knowledge.resolve_edt_field_type``) so generation emits the RIGHT type up front instead of
    leaning on the linter to catch a wrong one after the fact. Falls back to the historical
    heuristic + ``AxTableFieldString`` when there is no resolver or the EDT is not resolvable — so
    behaviour is unchanged without an index."""
    if resolver is not None:
        resolved = resolver(edt)
        if resolved:
            return resolved
    lowered = edt.lower()
    if lowered in {"refrecid", "int64"} or lowered.endswith("recid"):
        return "AxTableFieldInt64"
    if lowered in {"noyesid"}:
        return "AxTableFieldEnum"
    return "AxTableFieldString"


def _new_table_field_element(field: dict[str, str], resolver: FieldTypeResolver | None = None) -> ET.Element:
    edt_name = field["extended_data_type"]
    enum_fn = getattr(resolver, "enum_name", None)
    enum = enum_fn(edt_name) if enum_fn else None
    element = ET.Element("AxTableField")
    type_attr = "{http://www.w3.org/2001/XMLSchema-instance}type"
    element.set(type_attr, "AxTableFieldEnum" if enum else _table_field_type_for_edt(edt_name, resolver))
    name = ET.SubElement(element, "Name")
    name.text = field["name"]
    if enum:  # base-enum field -> <EnumType>
        ET.SubElement(element, "EnumType").text = enum
    else:
        ET.SubElement(element, "ExtendedDataType").text = edt_name
    return element


def _render_class_extension(plan: ArtifactPlan) -> str:
    extension_function = _extension_function_for_target_kind(plan.target_kind)
    methods = "\n".join(_render_method(method) for method in plan.methods) or "\t\t<Methods />"
    return f"""<?xml version="1.0" encoding="utf-8"?>
<AxClass xmlns:i="http://www.w3.org/2001/XMLSchema-instance">
\t<Name>{plan.artifact_name}</Name>
\t<SourceCode>
\t\t<Declaration><![CDATA[
[ExtensionOf({extension_function}({plan.target_object}))]
final class {plan.artifact_name}
{{
}}
]]></Declaration>
\t\t<Methods>
{methods}
\t\t</Methods>
\t</SourceCode>
</AxClass>
"""


def _render_method(method: dict[str, str]) -> str:
    name = method["name"]
    qualifiers = method.get("qualifiers") or method.get("visibility", "public")
    return_type = method.get("return_type", "void")
    signature = method.get("signature", f"{name}()")
    if "(" not in signature:
        signature = f"{name}()"
    body = _method_stub_body(name, return_type)
    return (
        "\t\t\t<Method>\n"
        f"\t\t\t\t<Name>{name}</Name>\n"
        "\t\t\t\t<Source><![CDATA[\n"
        f"    {qualifiers} {return_type} {signature.strip()}\n"
        "    {\n"
        f"{body}\n"
        "    }\n"
        "]]></Source>\n"
        "\t\t\t</Method>"
    )


def _method_stub_body(name: str, return_type: str) -> str:
    """A COMPILABLE stub body for the agent to fill in. CoC-style overrides chain via `next`; any
    other non-void method declares a typed local and returns it (valid X++ for primitives, EDTs,
    tables and classes alike), so the generated class compiles before the logic is written."""
    if name in {"delete", "insert", "update", "validateWrite", "validateField"}:
        return f"        next {name}();"
    rt = (return_type or "void").strip()
    if not rt or rt.lower() == "void":
        return "        // TODO: implement business logic."
    return f"        {rt} _ret;\n        // TODO: implement business logic.\n        return _ret;"


def _extension_function_for_target_kind(target_kind: str) -> str:
    return {
        "class": "classStr",
        "form": "formStr",
        "query": "queryStr",
        "menu-item-display": "menuItemDisplayStr",
        "menu-item-action": "menuItemActionStr",
        "menu-item-output": "menuItemOutputStr",
    }.get(target_kind, "tableStr")


def _render_data_entity(plan: ArtifactPlan) -> str:
    public_entity_name = plan.public_entity_name or plan.artifact_name
    public_collection_name = plan.public_collection_name or f"{plan.artifact_name}s"
    return f"""<?xml version="1.0" encoding="utf-8"?>
<AxDataEntityView xmlns:i="http://www.w3.org/2001/XMLSchema-instance">
\t<Name>{plan.artifact_name}</Name>
\t<SourceCode>
\t\t<Declaration><![CDATA[
public class {plan.artifact_name} extends common
{{
}}
]]></Declaration>
\t\t<Methods />
\t</SourceCode>
\t<DataManagementEnabled>Yes</DataManagementEnabled>
\t<IsPublic>Yes</IsPublic>
\t<PublicCollectionName>{public_collection_name}</PublicCollectionName>
\t<PublicEntityName>{public_entity_name}</PublicEntityName>
\t<FieldGroups />
\t<Fields />
\t<Keys />
\t<Mappings />
\t<Ranges />
\t<Relations />
\t<StateMachines />
</AxDataEntityView>
"""


def _render_service(plan: ArtifactPlan) -> str:
    operations = "\n".join(_render_service_operation(operation) for operation in plan.operations) or "\t<Operations />"
    return f"""<?xml version="1.0" encoding="utf-8"?>
<AxService xmlns:i="http://www.w3.org/2001/XMLSchema-instance">
\t<Name>{plan.artifact_name}</Name>
\t<Class>{plan.service_class or plan.target_object or plan.artifact_name}</Class>
\t<Operations>
{operations}
\t</Operations>
</AxService>
"""


def _render_service_group(plan: ArtifactPlan) -> str:
    services = "\n".join(_render_service_reference(service) for service in plan.services) or "\t<Services />"
    auto_deploy_line = f"\t<AutoDeploy>{plan.auto_deploy}</AutoDeploy>\n" if plan.auto_deploy else ""
    return f"""<?xml version="1.0" encoding="utf-8"?>
<AxServiceGroup xmlns:i="http://www.w3.org/2001/XMLSchema-instance">
\t<Name>{plan.artifact_name}</Name>
{auto_deploy_line}\t<Services>
{services}
\t</Services>
</AxServiceGroup>
"""


def _render_form_extension(plan: ArtifactPlan) -> str:
    controls = "\n".join(_render_form_extension_control(control) for control in plan.controls) or "\t<Controls />"
    return f"""<?xml version="1.0" encoding="utf-8"?>
<AxFormExtension xmlns:i="http://www.w3.org/2001/XMLSchema-instance" xmlns="Microsoft.Dynamics.AX.Metadata.V6">
\t<Name>{plan.artifact_name}</Name>
\t<ControlModifications />
\t<Controls>
{controls}
\t</Controls>
\t<DataSourceModifications />
\t<DataSourceReferences />
\t<DataSources />
\t<Parts />
\t<PropertyModifications />
</AxFormExtension>
"""


def _render_query(plan: ArtifactPlan) -> str:
    allow_cross_company_line = f"\t<AllowCrossCompany>{plan.allow_cross_company}</AllowCrossCompany>\n" if plan.allow_cross_company else ""
    root_name = plan.root_data_source or plan.root_table or "RootDataSource"
    root_table = plan.root_table or plan.root_data_source or "UnknownTable"
    order_by = _render_query_order_by(plan)
    return f"""<?xml version="1.0" encoding="utf-8"?>
<AxQuery xmlns:i="http://www.w3.org/2001/XMLSchema-instance" xmlns="" i:type="AxQuerySimple">
\t<Name>{plan.artifact_name}</Name>
\t<SourceCode>
\t\t<Methods>
\t\t\t<Method>
\t\t\t\t<Name>classDeclaration</Name>
\t\t\t\t<Source><![CDATA[
[Query]
public class {plan.artifact_name} extends QueryRun
{{
}}
]]></Source>
\t\t\t</Method>
\t\t</Methods>
\t</SourceCode>
{allow_cross_company_line}\t<DataSources>
\t\t<AxQuerySimpleRootDataSource>
\t\t\t<Name>{root_name}</Name>
\t\t\t<DynamicFields>Yes</DynamicFields>
\t\t\t<Table>{root_table}</Table>
\t\t\t<DataSources />
\t\t\t<DerivedDataSources />
\t\t\t<Fields />
\t\t\t<Ranges />
\t\t\t<GroupBy />
\t\t\t<Having />
\t\t\t<OrderBy>
{order_by}\t\t\t</OrderBy>
\t\t</AxQuerySimpleRootDataSource>
\t</DataSources>
</AxQuery>
"""


def _render_menu_item_display(plan: ArtifactPlan) -> str:
    label_line = f"\t<Label>{plan.label}</Label>\n" if plan.label else ""
    return f"""<?xml version="1.0" encoding="utf-8"?>
<AxMenuItemDisplay xmlns:i="http://www.w3.org/2001/XMLSchema-instance" xmlns="Microsoft.Dynamics.AX.Metadata.V1">
\t<Name>{plan.artifact_name}</Name>
{label_line}\t<Object>{plan.target_object}</Object>
\t<SubscriberAccessLevel>
\t\t<Read xmlns="">Allow</Read>
\t</SubscriberAccessLevel>
</AxMenuItemDisplay>
"""


def _render_menu_item_action(plan: ArtifactPlan) -> str:
    label_line = f"\t<Label>{plan.label}</Label>\n" if plan.label else ""
    object_type = _menu_item_object_type(plan.target_kind)
    return f"""<?xml version="1.0" encoding="utf-8"?>
<AxMenuItemAction xmlns:i="http://www.w3.org/2001/XMLSchema-instance" xmlns="Microsoft.Dynamics.AX.Metadata.V1">
\t<Name>{plan.artifact_name}</Name>
{label_line}\t<Object>{plan.target_object}</Object>
\t<ObjectType>{object_type}</ObjectType>
\t<SubscriberAccessLevel>
\t\t<Read xmlns="">Allow</Read>
\t</SubscriberAccessLevel>
</AxMenuItemAction>
"""


def _render_menu_item_output(plan: ArtifactPlan) -> str:
    object_type = _menu_item_object_type(plan.target_kind)
    configuration_key_line = f"\t<ConfigurationKey>{plan.configuration_key}</ConfigurationKey>\n" if plan.configuration_key else ""
    label_line = f"\t<Label>{plan.label}</Label>\n" if plan.label else ""
    linked_permission_object_line = (
        f"\t<LinkedPermissionObject>{plan.linked_permission_object}</LinkedPermissionObject>\n"
        if plan.linked_permission_object
        else ""
    )
    linked_permission_object_child_line = (
        f"\t<LinkedPermissionObjectChild>{plan.linked_permission_object_child}</LinkedPermissionObjectChild>\n"
        if plan.linked_permission_object_child
        else ""
    )
    linked_permission_type_line = (
        f"\t<LinkedPermissionType>{plan.linked_permission_type}</LinkedPermissionType>\n"
        if plan.linked_permission_type
        else ""
    )
    return f"""<?xml version="1.0" encoding="utf-8"?>
<AxMenuItemOutput xmlns:i="http://www.w3.org/2001/XMLSchema-instance" xmlns="Microsoft.Dynamics.AX.Metadata.V1">
\t<Name>{plan.artifact_name}</Name>
{configuration_key_line}{label_line}{linked_permission_object_line}{linked_permission_object_child_line}{linked_permission_type_line}\t<Object>{plan.target_object}</Object>
\t<ObjectType>{object_type}</ObjectType>
\t<SubscriberAccessLevel>
\t\t<Read xmlns="">Allow</Read>
\t</SubscriberAccessLevel>
</AxMenuItemOutput>
"""


def _render_security_privilege(plan: ArtifactPlan) -> str:
    entries = "\n".join(_render_entry_point(entry) for entry in plan.entry_points) or "\t\t<EntryPoints />"
    return f"""<?xml version="1.0" encoding="utf-8"?>
<AxSecurityPrivilege xmlns:i="http://www.w3.org/2001/XMLSchema-instance">
\t<Name>{plan.artifact_name}</Name>
\t<DataEntityPermissions />
\t<DirectAccessPermissions />
\t<EntryPoints>
{entries}
\t</EntryPoints>
\t<FormControlOverrides />
</AxSecurityPrivilege>
"""


def _render_security_duty_extension(plan: ArtifactPlan) -> str:
    privileges = "\n".join(_render_privilege_reference(privilege) for privilege in plan.privileges) or "\t\t<Privileges />"
    return f"""<?xml version="1.0" encoding="utf-8"?>
<AxSecurityDutyExtension xmlns:i="http://www.w3.org/2001/XMLSchema-instance">
\t<Name>{plan.artifact_name}</Name>
\t<Privileges>
{privileges}
\t</Privileges>
\t<PropertyModifications />
</AxSecurityDutyExtension>
"""


def _render_security_role_extension(plan: ArtifactPlan) -> str:
    duties = "\n".join(_render_duty_reference(duty) for duty in plan.duties) or "\t\t<Duties />"
    privileges = "\n".join(_render_privilege_reference(privilege) for privilege in plan.privileges) or "\t\t<Privileges />"
    return f"""<?xml version="1.0" encoding="utf-8"?>
<AxSecurityRoleExtension xmlns:i="http://www.w3.org/2001/XMLSchema-instance">
\t<Name>{plan.artifact_name}</Name>
\t<DirectAccessPermissions />
\t<Duties>
{duties}
\t</Duties>
\t<Privileges>
{privileges}
\t</Privileges>
\t<PropertyModifications />
</AxSecurityRoleExtension>
"""


def _render_entry_point(entry: dict[str, str]) -> str:
    object_type = entry["object_type"]
    object_name = entry["object_name"]
    return (
        "\t\t<AxSecurityEntryPointReference>\n"
        f"\t\t\t<Name>{object_name}</Name>\n"
        "\t\t\t<Grant>\n"
        "\t\t\t\t<Read>Allow</Read>\n"
        "\t\t\t</Grant>\n"
        f"\t\t\t<ObjectName>{object_name}</ObjectName>\n"
        f"\t\t\t<ObjectType>{object_type}</ObjectType>\n"
        "\t\t</AxSecurityEntryPointReference>"
    )


def _render_privilege_reference(privilege: dict[str, str]) -> str:
    return (
        "\t\t<AxSecurityPrivilegeReference>\n"
        f"\t\t\t<Name>{privilege['name']}</Name>\n"
        "\t\t</AxSecurityPrivilegeReference>"
    )


def _render_duty_reference(duty: dict[str, str]) -> str:
    return (
        "\t\t<AxSecurityDutyReference>\n"
        f"\t\t\t<Name>{duty['name']}</Name>\n"
        "\t\t</AxSecurityDutyReference>"
    )


def _menu_item_object_type(target_kind: str) -> str:
    mapping = {
        "class": "Class",
        "form": "Form",
        "report": "Report",
        "query": "Query",
    }
    return mapping.get(target_kind, target_kind[:1].upper() + target_kind[1:] if target_kind else "Class")


def _render_form_extension_control(control: dict[str, str]) -> str:
    control_id = f"FormExtensionControl{control['name']}"
    control_type, control_name = _form_control_type(control["control_type"])
    return (
        "\t\t<AxFormExtensionControl xmlns=\"\">\n"
        f"\t\t\t<Name>{control_id}</Name>\n"
        f"\t\t\t<FormControl xmlns=\"\" i:type=\"{control_type}\">\n"
        f"\t\t\t\t<Name>{control['name']}</Name>\n"
        f"\t\t\t\t<Type>{control_name}</Type>\n"
        "\t\t\t\t<FormControlExtension i:nil=\"true\" />\n"
        f"\t\t\t\t<DataField>{control['data_field']}</DataField>\n"
        f"\t\t\t\t<DataSource>{control['data_source']}</DataSource>\n"
        "\t\t\t</FormControl>\n"
        f"\t\t\t<Parent>{control['parent']}</Parent>\n"
        "\t\t</AxFormExtensionControl>"
    )


def _new_form_extension_control_element(control: dict[str, str]) -> ET.Element:
    control_id = f"FormExtensionControl{control['name']}"
    control_type, control_name = _form_control_type(control["control_type"])
    extension_control = ET.Element("AxFormExtensionControl")
    name = ET.SubElement(extension_control, "Name")
    name.text = control_id
    form_control = ET.SubElement(extension_control, "FormControl")
    form_control.set("{http://www.w3.org/2001/XMLSchema-instance}type", control_type)
    control_name_node = ET.SubElement(form_control, "Name")
    control_name_node.text = control["name"]
    type_node = ET.SubElement(form_control, "Type")
    type_node.text = control_name
    extension_node = ET.SubElement(form_control, "FormControlExtension")
    extension_node.set("{http://www.w3.org/2001/XMLSchema-instance}nil", "true")
    data_field = ET.SubElement(form_control, "DataField")
    data_field.text = control["data_field"]
    data_source = ET.SubElement(form_control, "DataSource")
    data_source.text = control["data_source"]
    parent = ET.SubElement(extension_control, "Parent")
    parent.text = control["parent"]
    return extension_control


def _form_control_type(control_type: str) -> tuple[str, str]:
    mapping = {
        "string": ("AxFormStringControl", "String"),
        "checkbox": ("AxFormCheckBoxControl", "CheckBox"),
        "combobox": ("AxFormComboBoxControl", "ComboBox"),
    }
    return mapping.get(control_type.lower(), ("AxFormStringControl", "String"))


def _render_query_order_by(plan: ArtifactPlan) -> str:
    if not plan.order_by:
        return ""
    root_name = plan.root_data_source or plan.root_table or "RootDataSource"
    return (
        "\t\t\t\t<AxQuerySimpleOrderByField>\n"
        f"\t\t\t\t\t<Name>{plan.order_by}</Name>\n"
        f"\t\t\t\t\t<DataSource>{root_name}</DataSource>\n"
        f"\t\t\t\t\t<Field>{plan.order_by}</Field>\n"
        "\t\t\t\t</AxQuerySimpleOrderByField>\n"
    )


def _render_query_root_datasource(plan: ArtifactPlan) -> str:
    root_name = plan.root_data_source or plan.root_table or "RootDataSource"
    root_table = plan.root_table or plan.root_data_source or "UnknownTable"
    order_by = _render_query_order_by(plan)
    return (
        "<AxQuerySimpleRootDataSource>"
        f"<Name>{root_name}</Name>"
        "<DynamicFields>Yes</DynamicFields>"
        f"<Table>{root_table}</Table>"
        "<DataSources />"
        "<DerivedDataSources />"
        "<Fields />"
        "<Ranges />"
        "<GroupBy />"
        "<Having />"
        f"<OrderBy>{order_by}</OrderBy>"
        "</AxQuerySimpleRootDataSource>"
    )


def _new_query_order_by_field(plan: ArtifactPlan) -> ET.Element:
    root_name = plan.root_data_source or plan.root_table or "RootDataSource"
    element = ET.Element("AxQuerySimpleOrderByField")
    name = ET.SubElement(element, "Name")
    name.text = plan.order_by
    datasource = ET.SubElement(element, "DataSource")
    datasource.text = root_name
    field = ET.SubElement(element, "Field")
    field.text = plan.order_by
    return element


def _render_service_operation(operation: dict[str, str]) -> str:
    return (
        "\t\t<AxServiceOperation>\n"
        f"\t\t\t<Name>{operation['name']}</Name>\n"
        f"\t\t\t<Method>{operation['method']}</Method>\n"
        "\t\t</AxServiceOperation>"
    )


def _render_service_reference(service: dict[str, str]) -> str:
    return (
        "\t\t<AxServiceReference>\n"
        f"\t\t\t<Name>{service['name']}</Name>\n"
        "\t\t</AxServiceReference>"
    )


def _merge_table_extension(plan: ArtifactPlan, existing_xml: str, resolver: FieldTypeResolver | None = None) -> str:
    root = ET.fromstring(existing_xml)
    fields = _ensure_child(root, "Fields")
    existing_names = {_child_text(field, "Name") for field in _children(fields, "AxTableField")}
    for field in plan.fields:
        if field["name"] in existing_names:
            continue
        fields.append(_new_table_field_element(field, resolver))
    return _serialize_xml(root)


def _merge_class_extension(plan: ArtifactPlan, existing_xml: str) -> str:
    root = ET.fromstring(existing_xml)
    source_code = _ensure_child(root, "SourceCode")
    methods = _ensure_child(source_code, "Methods")
    existing_names = {_child_text(method, "Name") for method in _children(methods, "Method")}
    for method in plan.methods:
        if method["name"] in existing_names:
            continue
        methods.append(ET.fromstring(_render_method(method)))
    return _serialize_xml(root)


def _merge_service(plan: ArtifactPlan, existing_xml: str) -> str:
    root = ET.fromstring(existing_xml)
    _upsert_child_text(root, "Name", plan.artifact_name)
    _upsert_child_text(root, "Class", plan.service_class or plan.target_object or plan.artifact_name)
    operations = _ensure_child(root, "Operations")
    existing_names = {_child_text(operation, "Name") for operation in _children(operations, "AxServiceOperation")}
    for operation in plan.operations:
        if operation["name"] in existing_names:
            continue
        operations.append(ET.fromstring(_render_service_operation(operation)))
    return _serialize_xml(root)


def _merge_service_group(plan: ArtifactPlan, existing_xml: str) -> str:
    root = ET.fromstring(existing_xml)
    _upsert_child_text(root, "Name", plan.artifact_name)
    if plan.auto_deploy:
        _upsert_child_text(root, "AutoDeploy", plan.auto_deploy)
    services = _ensure_child(root, "Services")
    existing_names = {_child_text(service, "Name") for service in _children(services, "AxServiceReference")}
    for service in plan.services:
        if service["name"] in existing_names:
            continue
        services.append(ET.fromstring(_render_service_reference(service)))
    return _serialize_xml(root)


def _merge_form_extension(plan: ArtifactPlan, existing_xml: str) -> str:
    root = ET.fromstring(existing_xml)
    controls = _ensure_child(root, "Controls")
    existing_names = {_child_text(control, "Name") for control in _children(controls, "AxFormExtensionControl")}
    existing_field_names = {_child_text(control, "DataField") for control in _children(controls, "AxFormExtensionControl")}
    for control in plan.controls:
        generated_name = f"FormExtensionControl{control['name']}"
        if generated_name in existing_names or control["data_field"] in existing_field_names:
            continue
        controls.append(_new_form_extension_control_element(control))
    return _serialize_xml(root)


def _merge_menu_item(plan: ArtifactPlan, existing_xml: str) -> str:
    root = ET.fromstring(existing_xml)
    _upsert_child_text(root, "Name", plan.artifact_name)
    if plan.label:
        _upsert_child_text(root, "Label", plan.label)
    _upsert_child_text(root, "Object", plan.target_object)
    if plan.family == "menu-item-action":
        _upsert_child_text(root, "ObjectType", _menu_item_object_type(plan.target_kind))
    return _serialize_xml(root)


def _merge_menu_item_output(plan: ArtifactPlan, existing_xml: str) -> str:
    root = ET.fromstring(existing_xml)
    _upsert_child_text(root, "Name", plan.artifact_name)
    if plan.configuration_key:
        _upsert_child_text(root, "ConfigurationKey", plan.configuration_key)
    if plan.label:
        _upsert_child_text(root, "Label", plan.label)
    if plan.linked_permission_object:
        _upsert_child_text(root, "LinkedPermissionObject", plan.linked_permission_object)
    if plan.linked_permission_object_child:
        _upsert_child_text(root, "LinkedPermissionObjectChild", plan.linked_permission_object_child)
    if plan.linked_permission_type:
        _upsert_child_text(root, "LinkedPermissionType", plan.linked_permission_type)
    _upsert_child_text(root, "Object", plan.target_object)
    _upsert_child_text(root, "ObjectType", _menu_item_object_type(plan.target_kind))
    return _serialize_xml(root)


def _merge_query(plan: ArtifactPlan, existing_xml: str) -> str:
    root = ET.fromstring(existing_xml)
    _upsert_child_text(root, "Name", plan.artifact_name)
    if plan.allow_cross_company:
        _upsert_child_text(root, "AllowCrossCompany", plan.allow_cross_company)

    datasources = _ensure_child(root, "DataSources")
    root_datasource = _first_child(datasources, "AxQuerySimpleRootDataSource")
    if root_datasource is None:
        root_datasource = ET.fromstring(_render_query_root_datasource(plan))
        datasources.append(root_datasource)
    else:
        if plan.root_data_source:
            _upsert_child_text(root_datasource, "Name", plan.root_data_source)
        if plan.root_table:
            _upsert_child_text(root_datasource, "Table", plan.root_table)
        order_by = _ensure_child(root_datasource, "OrderBy")
        if plan.order_by:
            existing_order_fields = {_child_text(field, "Field") for field in _children(order_by, "AxQuerySimpleOrderByField")}
            if plan.order_by not in existing_order_fields:
                order_by.append(_new_query_order_by_field(plan))
    return _serialize_xml(root)


def _merge_security_privilege(plan: ArtifactPlan, existing_xml: str) -> str:
    root = ET.fromstring(existing_xml)
    entry_points = _ensure_child(root, "EntryPoints")
    existing_keys = {
        (_child_text(entry, "ObjectType"), _child_text(entry, "ObjectName"))
        for entry in _children(entry_points, "AxSecurityEntryPointReference")
    }
    for entry in plan.entry_points:
        key = (entry["object_type"], entry["object_name"])
        if key in existing_keys:
            continue
        entry_points.append(ET.fromstring(_render_entry_point(entry)))
    return _serialize_xml(root)


def _merge_security_duty_extension(plan: ArtifactPlan, existing_xml: str) -> str:
    root = ET.fromstring(existing_xml)
    privileges = _ensure_child(root, "Privileges")
    existing_names = {_child_text(privilege, "Name") for privilege in _children(privileges, "AxSecurityPrivilegeReference")}
    for privilege in plan.privileges:
        if privilege["name"] in existing_names:
            continue
        privileges.append(ET.fromstring(_render_privilege_reference(privilege)))
    return _serialize_xml(root)


def _merge_security_role_extension(plan: ArtifactPlan, existing_xml: str) -> str:
    root = ET.fromstring(existing_xml)
    duties = _ensure_child(root, "Duties")
    privileges = _ensure_child(root, "Privileges")

    existing_duties = {_child_text(duty, "Name") for duty in _children(duties, "AxSecurityDutyReference")}
    existing_privileges = {_child_text(privilege, "Name") for privilege in _children(privileges, "AxSecurityPrivilegeReference")}

    for duty in plan.duties:
        if duty["name"] in existing_duties:
            continue
        duties.append(ET.fromstring(_render_duty_reference(duty)))

    for privilege in plan.privileges:
        if privilege["name"] in existing_privileges:
            continue
        privileges.append(ET.fromstring(_render_privilege_reference(privilege)))

    return _serialize_xml(root)


def _children(parent: ET.Element, local_name: str) -> list[ET.Element]:
    return [child for child in list(parent) if _local_name(child.tag) == local_name]


def _first_child(parent: ET.Element, local_name: str) -> ET.Element | None:
    for child in list(parent):
        if _local_name(child.tag) == local_name:
            return child
    return None


def _ensure_child(parent: ET.Element, local_name: str) -> ET.Element:
    for child in list(parent):
        if _local_name(child.tag) == local_name:
            return child
    child = ET.Element(_qualified_tag(parent, local_name))
    parent.append(child)
    return child


def _child_text(parent: ET.Element, local_name: str) -> str:
    for child in parent.iter():
        if _local_name(child.tag) == local_name and child.text:
            return child.text.strip()
    return ""


def _upsert_child_text(parent: ET.Element, local_name: str, value: str) -> None:
    for child in list(parent):
        if _local_name(child.tag) == local_name:
            child.text = value
            return
    child = ET.Element(_qualified_tag(parent, local_name))
    child.text = value
    parent.append(child)


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _qualified_tag(parent: ET.Element, local_name: str) -> str:
    if parent.tag.startswith("{"):
        namespace = parent.tag.split("}", 1)[0][1:]
        return f"{{{namespace}}}{local_name}"
    return local_name


def _serialize_xml(root: ET.Element) -> str:
    ET.register_namespace("i", "http://www.w3.org/2001/XMLSchema-instance")
    if root.tag.startswith("{"):
        namespace = root.tag.split("}", 1)[0][1:]
        ET.register_namespace("", namespace)
    return ET.tostring(root, encoding="unicode", xml_declaration=True)
