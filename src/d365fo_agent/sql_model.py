"""Query layer over an extracted SQL data model of a deployed D365 F&O database.

The model is a SQLite file produced by dumping a D365 Azure SQL database (read-only):
``sql_views`` (with full T-SQL definitions), ``sql_view_columns``, ``sql_view_dependencies``,
``sql_tables``, ``sql_table_columns``, ``sql_pk_columns`` — plus optional ANALYSIS tables
(``view_model``, ``model_view_tables``, ``functional_units``, ``functional_views``,
``unit_interfaces``) that classify each view against the AOT corpus and group tables into
functional units (invoice, settlement, financial dimensions, ...).

This module answers the question an agent actually asks: "what is the REAL SQL shape of this
entity/table, what does it sit on, and what business domain does it belong to" — grounding
OData/DMF/BYOD/reporting work in the physical model instead of guessed column lists.
Standard library only (``sqlite3``); the analysis tables are optional and degrade gracefully.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

_MAX_DEFINITION_CHARS = 20000


def _connect(db_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{Path(db_path)}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def _columns(conn: sqlite3.Connection, table: str, object_id: int) -> list[dict[str, object]]:
    return [
        {
            "name": r["name"], "type": r["type"], "max_length": r["max_length"],
            "precision": r["precision"], "scale": r["scale"], "nullable": bool(r["is_nullable"]),
        }
        for r in conn.execute(
            f"SELECT * FROM {table} WHERE object_id=? ORDER BY column_id", (object_id,)
        )
    ]


def get_sql_model(
    db_path: str | Path,
    name: str,
    *,
    include_definition: bool = False,
) -> dict[str, object]:
    """Look up ``name`` as a SQL view (entity counterpart) first, then as a base table."""
    db_path = Path(db_path)
    if not db_path.exists():
        return {"found": False, "error": f"SQL model database not found: {db_path}"}
    with _connect(db_path) as conn:
        view = conn.execute("SELECT * FROM sql_views WHERE UPPER(name)=UPPER(?)", (name,)).fetchone()
        if view is not None:
            return _describe_view(conn, view, include_definition)
        table = conn.execute("SELECT * FROM sql_tables WHERE UPPER(name)=UPPER(?)", (name,)).fetchone()
        if table is not None:
            return _describe_table(conn, table)
        # Suggest by shrinking prefix (full-name LIKE misses siblings such as *CDRENTITY variants).
        upper = name.upper()
        suggestions: list[str] = []
        for prefix in (upper, upper[:12], upper[:8]):
            suggestions = [r["name"] for r in conn.execute(
                "SELECT name FROM sql_views WHERE name LIKE ? ORDER BY name LIMIT 10", (f"{prefix}%",))]
            if suggestions:
                break
        return {"found": False, "name": name,
                "error": "not found as a SQL view or table", "suggestions": suggestions}


def _describe_view(conn: sqlite3.Connection, view: sqlite3.Row, include_definition: bool) -> dict[str, object]:
    result: dict[str, object] = {
        "found": True, "object": "view", "name": view["name"], "schema": view["schema_name"],
        "columns": _columns(conn, "sql_view_columns", view["object_id"]),
    }
    if _has_table(conn, "view_model"):
        vm = conn.execute("SELECT * FROM view_model WHERE object_id=?", (view["object_id"],)).fetchone()
        if vm is not None:
            result["kind"] = vm["kind"]  # entity | aot-view | other
            result["aot_name"] = vm["aot_name"]
    if _has_table(conn, "functional_views"):
        fv = conn.execute("SELECT * FROM functional_views WHERE view_name=?", (view["name"],)).fetchone()
        if fv is not None:
            result["functional_unit"] = fv["unit"]
            result["units_spanned"] = fv["units_spanned"]
    if _has_table(conn, "model_view_tables"):
        units = dict(conn.execute("SELECT table_name, unit FROM functional_units")) \
            if _has_table(conn, "functional_units") else {}
        result["base_tables"] = [
            {"table": r["table_name"], "via": r["via"], "unit": units.get(r["table_name"])}
            for r in conn.execute(
                "SELECT DISTINCT table_name, via FROM model_view_tables WHERE referencing_id=? ORDER BY table_name",
                (view["object_id"],))
        ]
    if include_definition and view["definition"]:
        definition = view["definition"]
        result["definition"] = definition[:_MAX_DEFINITION_CHARS]
        result["definition_truncated"] = len(definition) > _MAX_DEFINITION_CHARS
    return result


def _describe_table(conn: sqlite3.Connection, table: sqlite3.Row) -> dict[str, object]:
    result: dict[str, object] = {
        "found": True, "object": "table", "name": table["name"],
        "columns": _columns(conn, "sql_table_columns", table["object_id"]),
        "primary_key": [r["column_name"] for r in conn.execute(
            "SELECT column_name FROM sql_pk_columns WHERE object_id=? ORDER BY key_ordinal",
            (table["object_id"],))],
    }
    if _has_table(conn, "functional_units"):
        fu = conn.execute("SELECT unit FROM functional_units WHERE table_name=?", (table["name"],)).fetchone()
        if fu is not None:
            result["functional_unit"] = fu["unit"]
    if _has_table(conn, "model_view_tables"):
        refs = conn.execute(
            "SELECT view_name FROM model_view_tables WHERE table_name=? GROUP BY view_name "
            "ORDER BY view_name LIMIT 25", (table["name"],)).fetchall()
        count = conn.execute(
            "SELECT COUNT(DISTINCT view_name) FROM model_view_tables WHERE table_name=?",
            (table["name"],)).fetchone()[0]
        result["referenced_by_views"] = [r["view_name"] for r in refs]
        result["referenced_by_count"] = count
    return result


def sql_model_stats(db_path: str | Path) -> dict[str, object]:
    """Coverage summary of the SQL model (used by index_stats-style reporting)."""
    db_path = Path(db_path)
    if not db_path.exists():
        return {"available": False}
    with _connect(db_path) as conn:
        stats: dict[str, object] = {
            "available": True,
            "views": conn.execute("SELECT COUNT(*) FROM sql_views").fetchone()[0],
            "tables": conn.execute("SELECT COUNT(*) FROM sql_tables").fetchone()[0],
        }
        if _has_table(conn, "functional_units"):
            stats["functional_units"] = conn.execute(
                "SELECT COUNT(DISTINCT unit) FROM functional_units").fetchone()[0]
        return stats
