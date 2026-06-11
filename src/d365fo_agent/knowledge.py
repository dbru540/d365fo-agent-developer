"""High-level D365 knowledge queries built on top of the SQLite index.

These are the functions the MCP server exposes to a coding agent. Each one answers a
question the agent would otherwise *guess* at — and guessing is exactly how X++ generation
goes wrong (a hallucinated method name, a missing extension hop, a wrong security wiring).

Everything here is read-only and JSON-serialisable. File contents (for signatures) are read
on demand from the filesystem so the index itself stays lean.
"""

from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree as ET

from d365fo_agent.index_store import D365Index


# --- file resolution ----------------------------------------------------------------

def _resolve_file(relative_path: str | None, roots: list[Path]) -> Path | None:
    if not relative_path:
        return None
    rel = relative_path.replace("\\", "/")
    # Custom paths are stored relative to the repo root; standard paths relative to
    # PackagesLocalDirectory. Trying every configured root resolves both uniformly.
    for root in roots:
        candidate = root / rel
        if candidate.exists():
            return candidate
    return None


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _attr_local(el: ET.Element, name: str) -> str | None:
    for key, value in el.attrib.items():
        if _local(key) == name:
            return value
    return None


# --- EDT base-type resolution -------------------------------------------------------

# Concrete EDT subtype (root tag, or the root's i:type attribute) -> AOT table-field type.
_EDT_SUBTYPE_TO_FIELD = {
    "AxEdtInt": "AxTableFieldInt",
    "AxEdtInt64": "AxTableFieldInt64",
    "AxEdtReal": "AxTableFieldReal",
    "AxEdtString": "AxTableFieldString",
    "AxEdtDate": "AxTableFieldDate",
    "AxEdtTime": "AxTableFieldTime",
    "AxEdtUtcDateTime": "AxTableFieldUtcDateTime",
    "AxEdtGuid": "AxTableFieldGuid",
    "AxEdtContainer": "AxTableFieldContainer",
    "AxEdtEnum": "AxTableFieldEnum",
}


def resolve_edt_field_type(index: D365Index, edt: str, roots: list[Path]) -> str | None:
    """Map an EDT name to the concrete AOT table-field type (``AxTableFieldReal``/``…Date``/…).

    The standard corpus indexes *every* EDT under the generic ``AxEdt`` type, with the real
    subtype only in the root element's ``i:type`` attribute (``<AxEdt i:type="AxEdtReal">``), so we
    must READ the EDT's XML to know its base type — the index ``artifact_type`` alone is not enough.
    Custom EDTs stored under a subtype-specific folder (``AxEdtReal/…``) map directly. An enum EDT
    (or an ``AxEnum``) yields ``AxTableFieldEnum``. Returns ``None`` when unresolved (caller falls
    back) — never guesses.
    """
    matches = index.lookup_exact(edt)
    if not matches:
        return None
    artifact = matches[0]
    atype = artifact.get("artifact_type", "")
    if atype == "AxEnum":
        return "AxTableFieldEnum"
    if atype in _EDT_SUBTYPE_TO_FIELD:  # custom EDT under a subtype-specific folder
        return _EDT_SUBTYPE_TO_FIELD[atype]
    if atype.startswith("AxEdt"):  # standard EDT under the generic 'AxEdt' folder — read i:type
        path = _resolve_file(artifact.get("relative_path"), roots)
        if path is None:
            return None
        try:
            root = ET.fromstring(path.read_text(encoding="utf-8", errors="ignore"))
        except ET.ParseError:
            return None
        subtype = _attr_local(root, "type") or _local(root.tag)
        return _EDT_SUBTYPE_TO_FIELD.get(subtype)
    return None


def _iter(root: ET.Element, name: str):
    return (el for el in root.iter() if _local(el.tag) == name)


def _text(root: ET.Element, name: str) -> str | None:
    for el in root.iter():
        if _local(el.tag) == name and el.text:
            return el.text.strip()
    return None


# --- signature ----------------------------------------------------------------------

def get_signature(index: D365Index, name: str, roots: list[Path], artifact_type: str | None = None) -> dict[str, object]:
    """Return the concrete shape of an AOT element: methods, fields, operations, key props.

    This is what lets the agent call a real method with the real signature instead of
    inventing one. Returns ``{"found": False}`` when the element is unknown — a signal the
    agent should treat as "do not reference this".
    """
    matches = index.lookup_exact(name, artifact_type)
    if not matches:
        return {"found": False, "name": name, "artifact_type": artifact_type}
    artifact = matches[0]
    result: dict[str, object] = {
        "found": True,
        "name": artifact["name"],
        "artifact_type": artifact["artifact_type"],
        "model": artifact.get("model"),
        "package": artifact.get("package"),
        "classification": artifact.get("classification"),
        "relative_path": artifact.get("relative_path"),
        "label": artifact.get("label"),
        "is_public": artifact.get("is_public"),
        "data_management_enabled": artifact.get("data_management_enabled"),
        "methods": [],
        "fields": [],
        "operations": [],
        "extends": None,
        "declaration": None,
    }
    path = _resolve_file(artifact.get("relative_path"), roots)
    if path is None:
        result["source_available"] = False
        return result
    result["source_available"] = True
    try:
        root = ET.fromstring(path.read_text(encoding="utf-8", errors="ignore"))
    except ET.ParseError:
        result["parse_error"] = True
        return result

    declaration = _text(root, "Declaration")
    if declaration:
        result["declaration"] = "\n".join(declaration.splitlines()[:6])
        import re

        m = re.search(r"ExtensionOf\(\s*\w+\(([A-Za-z0-9_]+)\)", declaration)
        if m:
            result["extends"] = m.group(1)
        m2 = re.search(r"\bextends\s+([A-Za-z0-9_]+)", declaration)
        if m2 and not result["extends"]:
            result["extends"] = m2.group(1)

    methods: list[dict[str, str]] = []
    for method in _iter(root, "Method"):
        mname = None
        signature = None
        for child in method:
            if _local(child.tag) == "Name" and child.text:
                mname = child.text.strip()
            if _local(child.tag) == "Source" and child.text:
                for line in child.text.splitlines():
                    stripped = line.strip()
                    if stripped and "(" in stripped and not stripped.startswith(("[", "/", "{")):
                        signature = stripped
                        break
        if mname:
            methods.append({"name": mname, "signature": signature or f"{mname}()"})
    result["methods"] = methods[:200]

    fields: list[dict[str, str]] = []
    for field in _iter(root, "AxTableField"):
        fname = None
        edt = None
        for child in field:
            if _local(child.tag) == "Name" and child.text:
                fname = child.text.strip()
            if _local(child.tag) == "ExtendedDataType" and child.text:
                edt = child.text.strip()
        if fname:
            fields.append({"name": fname, "extended_data_type": edt or ""})
    result["fields"] = fields[:300]

    operations: list[dict[str, str]] = []
    for op in _iter(root, "AxServiceOperation"):
        oname = None
        omethod = None
        for child in op:
            if _local(child.tag) == "Name" and child.text:
                oname = child.text.strip()
            if _local(child.tag) == "Method" and child.text:
                omethod = child.text.strip()
        if oname:
            operations.append({"name": oname, "method": omethod or oname})
    result["operations"] = operations
    return result


# --- relationships ------------------------------------------------------------------

def get_extension_chain(index: D365Index, name: str) -> dict[str, object]:
    """Walk the extension/inheritance relationships around an element.

    Answers "what does this extend, and what extends it?" — the question that decides
    whether a new change should be an extension, a CoC class, or an event handler.
    """
    relations = index.relations_of(name)
    extends: list[str] = []
    extended_by: list[str] = []
    related_tables: list[str] = []
    for r in relations:
        rtype = r["relation_type"]
        if rtype in ("extension-of", "extends"):
            if r["source"] == name:
                extends.append(r["target"])
            elif r["target"] == name:
                extended_by.append(r["source"])
        elif rtype == "related-table" and r["source"] == name:
            related_tables.append(r["target"])
    # Also surface extensions targeting this element by naming convention (X.<model>).
    for candidate in index.search(name, limit=50):
        cand_name = candidate["name"]
        if cand_name != name and (cand_name.startswith(name + ".") or cand_name == f"{name}_Extension"):
            if cand_name not in extended_by:
                extended_by.append(cand_name)
    return {
        "name": name,
        "extends": sorted(set(extends)),
        "extended_by": sorted(set(extended_by)),
        "related_tables": sorted(set(related_tables)),
    }


def get_security_links(index: D365Index, name: str) -> dict[str, object]:
    """Surface the security graph around an element: what it secures, and what secures it."""
    relations = index.relations_of(name)
    secures: list[str] = []
    secured_by: list[str] = []
    for r in relations:
        if r["relation_type"] == "secured-by":
            if r["source"] == name:
                secures.append(r["target"])
            elif r["target"] == name:
                secured_by.append(r["source"])
    # Privileges whose entry points reference this element (target = "Type:Name").
    for r in index.relations_of(name):
        if r["relation_type"] == "secured-by" and r["target"].endswith(f":{name}"):
            secured_by.append(r["source"])
    return {
        "name": name,
        "secures": sorted(set(secures)),
        "secured_by": sorted(set(secured_by)),
    }


def get_entity_exposure(index: D365Index, name: str) -> dict[str, object]:
    """Report OData / data-management exposure for a data entity or table."""
    matches = index.lookup_exact(name)
    if not matches:
        return {"found": False, "name": name}
    artifact = matches[0]
    exposed_relations = [
        r for r in index.relations_of(name)
        if r["relation_type"] in ("exposed-as-entity", "exposed-as-public-collection")
    ]
    return {
        "found": True,
        "name": artifact["name"],
        "artifact_type": artifact["artifact_type"],
        "is_public": artifact.get("is_public"),
        "data_management_enabled": artifact.get("data_management_enabled"),
        "public_entity_name": artifact.get("public_entity_name"),
        "public_collection_name": artifact.get("public_collection_name"),
        "exposure_relations": exposed_relations,
    }


# --- examples -----------------------------------------------------------------------

def find_similar_examples(
    index: D365Index,
    query: str,
    roots: list[Path],
    *,
    artifact_type: str | None = None,
    limit: int = 5,
    include_content: bool = False,
) -> dict[str, object]:
    """Retrieve idiomatic in-corpus examples for a task.

    Strategy is exact-and-symbolic first (FTS over the corpus, custom code ranked above
    standard), NOT semantic similarity — for X++ the right example is found by name/type
    overlap and graph proximity, and vector recall would only add hallucination risk.
    """
    results = index.search(query, artifact_type=artifact_type, limit=limit)
    examples: list[dict[str, object]] = []
    for artifact in results:
        entry = dict(artifact)
        if include_content:
            path = _resolve_file(artifact.get("relative_path"), roots)
            if path is not None:
                try:
                    entry["content"] = path.read_text(encoding="utf-8", errors="ignore")[:20000]
                except OSError:
                    entry["content"] = None
        examples.append(entry)
    return {"query": query, "artifact_type": artifact_type, "count": len(examples), "examples": examples}


def _set_direct_child(xml: str, key: str, value: str) -> tuple[str, str]:
    """Set a top-level ``<key>`` element's text on AOT XML, preserving the rest verbatim. Replaces
    the first existing ``<key>…</key>`` if present, else inserts after the root ``</Name>``."""
    import re

    new_xml, n = re.subn(rf"<{re.escape(key)}>.*?</{re.escape(key)}>", f"<{key}>{value}</{key}>", xml, count=1, flags=re.DOTALL)
    if n:
        return new_xml, "set"
    new_xml, n = re.subn(r"(</Name>\n)", rf"\1\t<{key}>{value}</{key}>\n", xml, count=1)
    if n:
        return new_xml, "inserted"
    return xml, "skipped"


def scaffold_object(
    index: D365Index,
    artifact_type: str,
    roots: list[Path],
    *,
    new_name: str | None = None,
    query: str | None = None,
    properties: dict[str, str] | None = None,
    limit: int = 8,
) -> dict[str, object]:
    """Return a real corpus example of ``artifact_type`` as a starting skeleton for a NEW object.

    This is the "help me code a <type>" affordance for the WHOLE AOT — it works for any object
    type the index covers (AxView, AxWorkflowApproval, AxEnumExtension, AxAggregateMeasurement,
    AxTile, …), not just the families with a hand-written generator, because it clones a real
    example rather than templating. ``new_name`` renames the root ``<Name>`` (verbatim swap, the
    rest preserved); ``properties`` sets top-level elements on the skeleton (e.g.
    ``{"Label": "@MyLabels:Foo", "ConfigurationKey": "LedgerBasic"}`` — replaced if present, else
    inserted after ``<Name>``); ``query`` biases example selection toward a relevant one. Returns
    ``{found, artifact_type, based_on, new_name, xml, changes, note}`` — a *scaffold* to adapt and
    then verify, never a finished artifact.
    """
    candidates = (
        index.search(query, artifact_type=artifact_type, limit=limit)
        if query else index.sample_by_type(artifact_type, limit=limit)
    )
    if not candidates:
        return {
            "found": False, "artifact_type": artifact_type, "new_name": new_name,
            "hint": f"No '{artifact_type}' example is indexed. Confirm the exact AOT type name with "
                    "index_stats / search_corpus — type folders are named 'Ax<Type>'.",
        }
    for cand in candidates:
        path = _resolve_file(cand.get("relative_path"), roots)
        if path is None:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
            root = ET.fromstring(text)
        except ET.ParseError:
            continue
        source_name = next((c.text.strip() for c in root if _local(c.tag) == "Name" and c.text), None)
        changes: list[str] = []
        if new_name and source_name:
            import re

            text, n = re.subn(rf"<Name>{re.escape(source_name)}</Name>", f"<Name>{new_name}</Name>", text, count=1)
            if n:
                changes.append(f"<Name> {source_name} -> {new_name}")
        for key, value in (properties or {}).items():
            text, action = _set_direct_child(text, key, value)
            changes.append(f"<{key}> {action} -> {value}")
        return {
            "found": True, "artifact_type": artifact_type,
            "based_on": cand["name"], "based_on_source": cand.get("source"),
            "new_name": new_name or source_name, "xml": text, "changes": changes,
            "note": "Starting scaffold cloned from a real corpus example — ADAPT it. It is NOT a "
                    "finished artifact: rename the remaining identifiers/labels, verify every "
                    "referenced element with element_exists, then run validate_xml + lint_artifact "
                    "(+ compile_model) before using it.",
        }
    return {
        "found": True, "source_available": False, "artifact_type": artifact_type,
        "based_on": candidates[0]["name"],
        "hint": "Examples of this type are indexed but their XML files were not found under the configured roots.",
    }
