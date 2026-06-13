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
    if _has_table(conn, "sql_unique_index_columns"):
        keys: dict[str, list[str]] = {}
        for r in conn.execute(
            "SELECT index_name, column_name FROM sql_unique_index_columns "
            "WHERE table_name=? ORDER BY index_name, key_ordinal", (table["name"],)):
            keys.setdefault(r["index_name"], []).append(r["column_name"])
        result["alternate_keys"] = [{"index": k, "columns": v} for k, v in keys.items()]
    if _has_table(conn, "sql_table_rowcounts"):
        rc = conn.execute("SELECT row_count FROM sql_table_rowcounts WHERE table_name=?",
                          (table["name"],)).fetchone()
        if rc is not None:
            result["row_count"] = rc["row_count"]
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


def explore_functional_unit(db_path: str | Path, unit: str, *, top: int = 15) -> dict[str, object]:
    """Describe a functional unit (business domain): core tables, main entities, interfaces.

    Answers "what is the settlement domain and what does it connect to" — the unit inventory
    comes from the prefix-seeded + affinity-propagated classification stored in the model.
    """
    db_path = Path(db_path)
    if not db_path.exists():
        return {"found": False, "error": f"SQL model database not found: {db_path}"}
    with _connect(db_path) as conn:
        if not _has_table(conn, "functional_units"):
            return {"found": False, "error": "No functional analysis in this SQL model "
                    "(functional_units table absent)."}
        known = [r[0] for r in conn.execute(
            "SELECT DISTINCT unit FROM functional_units ORDER BY unit")]
        if unit not in known:
            close = [u for u in known if unit.lower() in u.lower()]
            return {"found": False, "unit": unit, "error": "unknown functional unit",
                    "suggestions": close or known}
        result: dict[str, object] = {
            "found": True, "unit": unit,
            "n_tables": conn.execute(
                "SELECT COUNT(*) FROM functional_units WHERE unit=?", (unit,)).fetchone()[0],
        }
        result["core_tables"] = [
            {"table": r["table_name"], "referenced_by_views": r["refs"], "columns": r["cols"]}
            for r in conn.execute("""
                SELECT fu.table_name,
                  (SELECT COUNT(DISTINCT m.view_name) FROM model_view_tables m
                     WHERE m.table_name = fu.table_name) AS refs,
                  (SELECT COUNT(*) FROM sql_table_columns c JOIN sql_tables t
                     ON t.object_id = c.object_id WHERE t.name = fu.table_name) AS cols
                FROM functional_units fu WHERE fu.unit = ? ORDER BY refs DESC LIMIT ?""",
                (unit, top))
            if r["refs"] > 0
        ]
        if _has_table(conn, "functional_views"):
            result["n_views"] = conn.execute(
                "SELECT COUNT(*) FROM functional_views WHERE unit=?", (unit,)).fetchone()[0]
            result["entities"] = [r[0] for r in conn.execute("""
                SELECT fv.view_name FROM functional_views fv
                LEFT JOIN view_model vm ON vm.name = fv.view_name
                WHERE fv.unit = ? AND COALESCE(vm.kind, 'entity') = 'entity'
                ORDER BY COALESCE(vm.n_tables, 0) DESC LIMIT ?""", (unit, top))]
        if _has_table(conn, "unit_interfaces"):
            result["interfaces"] = [
                {"with": r["unit_b"] if r["unit_a"] == unit else r["unit_a"],
                 "bridge_views": r["n_views"], "examples": r["examples"]}
                for r in conn.execute("""
                    SELECT * FROM unit_interfaces WHERE unit_a = ? OR unit_b = ?
                    ORDER BY n_views DESC LIMIT ?""", (unit, unit, top))
            ]
        return result


def _classify_name(conn: sqlite3.Connection, name: str) -> tuple[str, str] | None:
    """Return (kind, canonical_name) where kind is 'view' or 'table', or None."""
    row = conn.execute("SELECT name FROM sql_views WHERE UPPER(name)=UPPER(?)", (name,)).fetchone()
    if row is not None:
        return ("view", row["name"])
    row = conn.execute("SELECT name FROM sql_tables WHERE UPPER(name)=UPPER(?)", (name,)).fetchone()
    if row is not None:
        return ("table", row["name"])
    return None


def find_relations(db_path: str | Path, a: str, b: str) -> dict[str, object]:
    """Explain how two objects relate: shared views for tables (the SQL proof of a join),
    shared base tables for entities, and the inter-unit interface when domains differ."""
    db_path = Path(db_path)
    if not db_path.exists():
        return {"found": False, "error": f"SQL model database not found: {db_path}"}
    with _connect(db_path) as conn:
        if not _has_table(conn, "model_view_tables"):
            return {"found": False, "error": "No dependency analysis in this SQL model "
                    "(model_view_tables absent)."}
        ka, kb = _classify_name(conn, a), _classify_name(conn, b)
        missing = [n for n, k in ((a, ka), (b, kb)) if k is None]
        if missing:
            return {"found": False, "error": f"not found as view or table: {', '.join(missing)}"}
        (kind_a, name_a), (kind_b, name_b) = ka, kb

        units = dict(conn.execute("SELECT table_name, unit FROM functional_units")) \
            if _has_table(conn, "functional_units") else {}
        view_units = dict(conn.execute("SELECT view_name, unit FROM functional_views")) \
            if _has_table(conn, "functional_views") else {}

        def unit_of(kind: str, name: str) -> str | None:
            return units.get(name) if kind == "table" else view_units.get(name)

        result: dict[str, object] = {
            "found": True,
            "a": {"name": name_a, "object": kind_a, "unit": unit_of(kind_a, name_a)},
            "b": {"name": name_b, "object": kind_b, "unit": unit_of(kind_b, name_b)},
        }

        if kind_a == "table" and kind_b == "table":
            joining = [r[0] for r in conn.execute("""
                SELECT view_name FROM model_view_tables WHERE table_name = ?
                INTERSECT SELECT view_name FROM model_view_tables WHERE table_name = ?
                ORDER BY view_name LIMIT 25""", (name_a, name_b))]
            result["relation"] = "joined_by_views"
            result["joining_views"] = joining
            result["joining_view_count"] = conn.execute("""
                SELECT COUNT(*) FROM (
                  SELECT view_name FROM model_view_tables WHERE table_name = ?
                  INTERSECT SELECT view_name FROM model_view_tables WHERE table_name = ?)""",
                (name_a, name_b)).fetchone()[0]
        elif kind_a == "view" and kind_b == "view":
            shared = [{"table": r[0], "unit": units.get(r[0])} for r in conn.execute("""
                SELECT table_name FROM model_view_tables WHERE view_name = ?
                INTERSECT SELECT table_name FROM model_view_tables WHERE view_name = ?
                ORDER BY table_name LIMIT 25""", (name_a, name_b))]
            result["relation"] = "share_base_tables"
            result["shared_tables"] = shared
        else:
            view, table = (name_a, name_b) if kind_a == "view" else (name_b, name_a)
            rows = conn.execute(
                "SELECT via FROM model_view_tables WHERE view_name = ? AND table_name = ?",
                (view, table)).fetchall()
            result["relation"] = "view_reads_table" if rows else "no_direct_dependency"
            result["via"] = sorted({r["via"] for r in rows})

        ua, ub = result["a"]["unit"], result["b"]["unit"]  # type: ignore[index]
        if ua and ub and ua != ub and _has_table(conn, "unit_interfaces"):
            x, y = sorted((ua, ub))
            iface = conn.execute(
                "SELECT n_views, examples FROM unit_interfaces WHERE unit_a=? AND unit_b=?",
                (x, y)).fetchone()
            if iface is not None:
                result["unit_interface"] = {"units": [x, y], "bridge_views": iface["n_views"],
                                            "examples": iface["examples"]}
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
