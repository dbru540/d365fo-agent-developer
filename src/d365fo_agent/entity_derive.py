"""Derive a custom public OData entity from a standard one — the "duplicate, expose, relabel,
secure" workflow that you cannot do by editing the standard entity in place.

Why this is a *clone*, not a *generate*: a real data entity is a large artifact (hundreds of
mapped fields, datasources, keys, methods). Regenerating it from a spec produces a useless stub
(the old `data-entity` render did exactly that — gap S03). The senior-dev pattern is to duplicate
the actual standard entity's XML and adjust only the handful of nodes that make it a new public
entity. This module does that faithfully, then builds the matching security privilege whose shape
is grounded on a real in-corpus example (DataEntityPermissions / AxSecurityDataEntityPermission).
"""

from __future__ import annotations

import re
from xml.etree import ElementTree as ET

_I_NS = "http://www.w3.org/2001/XMLSchema-instance"

# Direct-child order D365 expects on AxDataEntityView for the nodes we manage. New nodes are
# inserted in roughly this order; D365 re-sorts on import, so this is for human readability.
_ENTITY_NODE_ORDER = [
    "Name", "Label", "DataManagementEnabled", "DataManagementStagingTable",
    "IsPublic", "PrimaryKey", "PublicCollectionName", "PublicEntityName",
]


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _direct_child(root: ET.Element, local_name: str) -> ET.Element | None:
    for child in list(root):
        if _local(child.tag) == local_name:
            return child
    return None


def _upsert_direct(root: ET.Element, local_name: str, value: str) -> None:
    existing = _direct_child(root, local_name)
    if existing is not None:
        existing.text = value
        return
    el = ET.Element(local_name)
    el.text = value
    # insert near a sensible neighbour for readability
    try:
        idx = _ENTITY_NODE_ORDER.index(local_name)
        before = {n for n in _ENTITY_NODE_ORDER[idx + 1:]}
    except ValueError:
        before = set()
    children = list(root)
    pos = len(children)
    for i, child in enumerate(children):
        if _local(child.tag) in before:
            pos = i
            break
    root.insert(pos, el)


def _serialize(root: ET.Element) -> str:
    ET.register_namespace("i", _I_NS)
    if root.tag.startswith("{"):
        ET.register_namespace("", root.tag.split("}", 1)[0][1:])
    return ET.tostring(root, encoding="unicode", xml_declaration=True)


def derive_public_entity(
    source_xml: str,
    new_name: str,
    *,
    public_entity_name: str | None = None,
    public_collection_name: str | None = None,
    label: str | None = None,
    data_management: bool | None = None,
    staging_table: str | None = None,
) -> dict[str, object]:
    """Clone a standard entity's XML into a new public custom entity.

    Returns ``{xml, name, public_entity_name, public_collection_name, source_name,
    field_count, changes}``. Fields/datasources/keys/methods are preserved verbatim; only the
    identity/exposure/label nodes are adjusted, plus the backing class name in the declaration.
    """
    root = ET.fromstring(source_xml)
    source_name = (_direct_child(root, "Name").text or "").strip() if _direct_child(root, "Name") is not None else ""
    changes: list[str] = []

    _upsert_direct(root, "Name", new_name)
    changes.append(f"Name: {source_name} -> {new_name}")

    pen = public_entity_name or (new_name[:-6] if new_name.endswith("Entity") else new_name)
    pcn = public_collection_name or (pen + "s")
    _upsert_direct(root, "IsPublic", "Yes")
    _upsert_direct(root, "PublicEntityName", pen)
    _upsert_direct(root, "PublicCollectionName", pcn)
    changes.append(f"IsPublic=Yes, PublicEntityName={pen}, PublicCollectionName={pcn}")

    if label is not None:
        _upsert_direct(root, "Label", label)
        changes.append(f"Label -> {label}")
    if data_management is not None:
        _upsert_direct(root, "DataManagementEnabled", "Yes" if data_management else "No")
        changes.append(f"DataManagementEnabled={'Yes' if data_management else 'No'}")
        if staging_table:
            _upsert_direct(root, "DataManagementStagingTable", staging_table)
            changes.append(f"DataManagementStagingTable={staging_table}")

    # Rename the backing class in the declaration (the entity class name must equal the entity).
    declaration = None
    for el in root.iter():
        if _local(el.tag) == "Declaration":
            declaration = el
            break
    if declaration is not None and declaration.text and source_name:
        new_decl, n = re.subn(rf"\bclass\s+{re.escape(source_name)}\b", f"class {new_name}", declaration.text)
        if n:
            declaration.text = new_decl
            changes.append(f"declaration class {source_name} -> {new_name} ({n}x)")

    field_count = sum(1 for el in root.iter() if _local(el.tag) == "AxDataEntityViewField")

    return {
        "xml": _serialize(root),
        "name": new_name,
        "public_entity_name": pen,
        "public_collection_name": pcn,
        "source_name": source_name,
        "field_count": field_count,
        "changes": changes,
    }


def build_entity_privilege(
    entity_name: str,
    *,
    privilege_name: str | None = None,
    label: str | None = None,
    grants: list[str] | None = None,
    integration_mode: str = "OData",
) -> dict[str, object]:
    """Build a privilege that secures a data entity, using the real corpus shape
    (DataEntityPermissions / AxSecurityDataEntityPermission). Defaults to full CRUD for a
    read-write API entity; pass ``grants=["Read"]`` for read-only."""
    privilege_name = privilege_name or f"{entity_name}Privilege"
    grants = grants or ["Read", "Create", "Update", "Delete"]
    grant_xml = "\n".join(f"\t\t\t\t<{g}>Allow</{g}>" for g in grants)
    label_line = f"\t<Label>{label}</Label>\n" if label else ""
    xml = f"""<?xml version="1.0" encoding="utf-8"?>
<AxSecurityPrivilege xmlns:i="http://www.w3.org/2001/XMLSchema-instance">
\t<Name>{privilege_name}</Name>
{label_line}\t<DataEntityPermissions>
\t\t<AxSecurityDataEntityPermission>
\t\t\t<Grant>
{grant_xml}
\t\t\t</Grant>
\t\t\t<IntegrationMode>{integration_mode}</IntegrationMode>
\t\t\t<Name>{entity_name}</Name>
\t\t\t<Fields />
\t\t\t<Methods />
\t\t</AxSecurityDataEntityPermission>
\t</DataEntityPermissions>
\t<DirectAccessPermissions />
\t<EntryPoints />
\t<FormControlOverrides />
</AxSecurityPrivilege>
"""
    return {"xml": xml, "name": privilege_name, "entity": entity_name, "grants": grants, "integration_mode": integration_mode}


REVIEW_CHECKLIST = [
    "Entity & privilege names are prefixed with your model prefix (lint: naming-prefix).",
    "Top-level <Label> (and field labels you care about) point to YOUR model's label file, not the source's (lint: label-not-literal checks literals; cross-file label refs are not auto-rewritten).",
    "If DataManagementEnabled=Yes, the staging table exists or is created.",
    "Method bodies that reference the source entity class by name were not rewritten — review the SourceCode if any method hard-codes the old class name.",
    "Wire the privilege into a duty/role so it actually grants access — run wire_security (MCP) / `wire-security` (CLI) with this privilege name; a privilege alone grants nothing.",
    "Compile + Best-Practice on a Windows D365 host before shipping.",
]
