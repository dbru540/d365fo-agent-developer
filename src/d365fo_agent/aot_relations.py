"""Extract AOT table relations — the D365 equivalent of foreign keys.

AX business tables define no SQL foreign keys; the relational graph lives in the AOT
metadata: every ``AxTable`` (and ``AxTableExtension``) XML carries a ``<Relations>`` block
with the related table, the relationship type (Association/Composition), both cardinalities,
and the EXACT join fields (``<AxTableRelationConstraintField>``: Field ↔ RelatedField, plus
fixed-value constraints). This module walks one or more corpus roots (PackagesLocalDirectory
and/or editable source trees), parses those blocks, and stores them next to the SQL data
model so ``find_relations``/``get_sql_model`` can explain table relationships with the same
authority a foreign key would. Standard library only.
"""

from __future__ import annotations

import sqlite3
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Iterator

_XSI_TYPE = "{http://www.w3.org/2001/XMLSchema-instance}type"
# Mirrors index_store._NON_AOT_DIRS: build outputs that contain compiled XML copies.
_SKIP_DIRS = {"bin", "Descriptor", "Resources", "XppMetadata", "AdditionalFiles", "obj"}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS aot_relations(
    table_name TEXT, relation_name TEXT, related_table TEXT,
    relationship_type TEXT, cardinality TEXT, related_cardinality TEXT,
    edt_relation INTEGER, source_element TEXT,
    PRIMARY KEY(table_name, relation_name, source_element));
CREATE TABLE IF NOT EXISTS aot_relation_fields(
    table_name TEXT, relation_name TEXT, kind TEXT,
    field TEXT, related_field TEXT, fixed_value TEXT, source_edt TEXT);
CREATE INDEX IF NOT EXISTS ix_aot_rel_table ON aot_relations(table_name);
CREATE INDEX IF NOT EXISTS ix_aot_rel_related ON aot_relations(related_table);
"""


def _text(node: ET.Element | None) -> str | None:
    return node.text.strip() if node is not None and node.text else None


def _iter_table_files(root: Path) -> Iterator[tuple[Path, str]]:
    """Yield (xml_path, element_kind) for every AxTable/AxTableExtension under a corpus root."""
    for kind in ("AxTable", "AxTableExtension"):
        for type_dir in root.rglob(kind):
            if not type_dir.is_dir() or type_dir.name != kind:
                continue
            if any(part in _SKIP_DIRS for part in type_dir.relative_to(root).parts):
                continue
            for xml_file in type_dir.glob("*.xml"):
                yield xml_file, kind


def parse_table_relations(xml_path: Path, kind: str) -> tuple[str, str, list[dict[str, object]]]:
    """Parse one AxTable/AxTableExtension XML. Returns (table_name, source_element, relations).

    For an extension ``CustTable.MyModel``, the relations belong to ``CustTable``.
    """
    tree = ET.parse(xml_path)
    root = tree.getroot()
    element_name = _text(root.find("Name")) or xml_path.stem
    table_name = element_name.split(".")[0] if kind == "AxTableExtension" else element_name

    relations: list[dict[str, object]] = []
    for rel in root.iter("AxTableRelation"):
        constraints: list[dict[str, object]] = []
        for constraint in rel.iter("AxTableRelationConstraint"):
            ctype = (constraint.get(_XSI_TYPE) or "AxTableRelationConstraintField")
            constraints.append({
                "kind": ctype.replace("AxTableRelationConstraint", "").lower() or "field",
                "field": _text(constraint.find("Field")),
                "related_field": _text(constraint.find("RelatedField")),
                "fixed_value": _text(constraint.find("Value")),
                "source_edt": _text(constraint.find("SourceEDT")),
            })
        relations.append({
            "name": _text(rel.find("Name")),
            "related_table": _text(rel.find("RelatedTable")),
            "relationship_type": _text(rel.find("RelationshipType")),
            "cardinality": _text(rel.find("Cardinality")),
            "related_cardinality": _text(rel.find("RelatedTableCardinality")),
            "edt_relation": 1 if _text(rel.find("EDTRelation")) == "Yes" else 0,
            "constraints": constraints,
        })
    return table_name, element_name, relations


def extract_aot_relations(
    roots: "list[str | Path]",
    db_path: str | Path,
    *,
    progress: "callable[[str, int], None] | None" = None,
) -> dict[str, int]:
    """Walk every AxTable/AxTableExtension under ``roots`` and persist their relations."""
    conn = sqlite3.connect(Path(db_path))
    conn.executescript("DELETE FROM aot_relations; DELETE FROM aot_relation_fields;"
                       if conn.execute("SELECT 1 FROM sqlite_master WHERE name='aot_relations'").fetchone()
                       else "SELECT 1;")
    conn.executescript(_SCHEMA)

    files = relations_count = 0
    rel_rows: list[tuple] = []
    field_rows: list[tuple] = []
    for root in roots:
        root = Path(root)
        for xml_file, kind in _iter_table_files(root):
            try:
                table, element, relations = parse_table_relations(xml_file, kind)
            except OSError:
                # Windows MAX_PATH: deep AOT paths exceed 260 chars — retry extended-length.
                try:
                    table, element, relations = parse_table_relations(
                        Path("\\\\?\\" + str(xml_file.resolve())), kind)
                except (OSError, ET.ParseError):
                    continue
            except ET.ParseError:
                continue
            files += 1
            for rel in relations:
                if not rel["related_table"]:
                    continue
                relations_count += 1
                rel_rows.append((table, rel["name"], rel["related_table"],
                                 rel["relationship_type"], rel["cardinality"],
                                 rel["related_cardinality"], rel["edt_relation"], element))
                for c in rel["constraints"]:
                    field_rows.append((table, rel["name"], c["kind"], c["field"],
                                       c["related_field"], c["fixed_value"], c["source_edt"]))
            if len(rel_rows) >= 5000:
                conn.executemany("INSERT OR REPLACE INTO aot_relations VALUES(?,?,?,?,?,?,?,?)", rel_rows)
                conn.executemany("INSERT INTO aot_relation_fields VALUES(?,?,?,?,?,?,?)", field_rows)
                conn.commit()
                rel_rows, field_rows = [], []
                if progress:
                    progress(str(root), relations_count)
    conn.executemany("INSERT OR REPLACE INTO aot_relations VALUES(?,?,?,?,?,?,?,?)", rel_rows)
    conn.executemany("INSERT INTO aot_relation_fields VALUES(?,?,?,?,?,?,?)", field_rows)
    conn.commit()
    stats = {
        "files_parsed": files,
        "relations": conn.execute("SELECT COUNT(*) FROM aot_relations").fetchone()[0],
        "constraint_fields": conn.execute("SELECT COUNT(*) FROM aot_relation_fields").fetchone()[0],
        "tables_with_relations": conn.execute(
            "SELECT COUNT(DISTINCT table_name) FROM aot_relations").fetchone()[0],
    }
    conn.close()
    return stats
