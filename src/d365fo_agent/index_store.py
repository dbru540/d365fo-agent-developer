"""Persistent SQLite + FTS5 index over the D365 AOT corpus.

Why this exists
---------------
The in-memory catalog (`indexer.build_catalog`) re-parses the custom source tree on every
run. That is fine for the ~1k custom artifacts, but it does not scale to the full
``PackagesLocalDirectory`` (hundreds of thousands of standard artifacts) and it cannot be
queried by an out-of-process MCP server cheaply. This module gives the agent layer a
durable, fast, symbolic index:

* exact lookup by name/type  -> the #1 antidote to a model hallucinating a class/table name
* full-text search (BM25)    -> "what handles BFC export?" over names/labels/paths
* relation lookup            -> extension chains, security wiring, entity exposure

It is standard-library only (``sqlite3`` with the FTS5 extension, which ships with the
CPython Windows build). No server, one file on disk.
"""

from __future__ import annotations

import fnmatch
import sqlite3
from contextlib import closing
from dataclasses import asdict
from pathlib import Path
from typing import Iterable, Iterator

from d365fo_agent.models import Artifact, Catalog

SCHEMA_VERSION = 2

# EVERY real AOT element folder is named "Ax<Type>" (AxClass, AxView, AxWorkflowApproval,
# AxAggregateMeasurement, AxTile, AxDataEntityViewExtension, …). We index ALL of them rather than a
# hand-maintained whitelist, so the agent can be grounded on EVERY object type the corpus contains —
# present and future. A whitelist silently dropped ~50 types (thousands of real objects, including
# the *Extension families) and had to be edited for each new type; the "Ax*" rule needs no upkeep.
# These are the only non-AOT directories that sit alongside the type folders — skip them as noise.
_NON_AOT_DIRS = {"bin", "Descriptor", "Resources", "XppMetadata", "AdditionalFiles", "obj"}


def _is_aot_type_dir(path: Path) -> bool:
    """An AOT element folder: a directory whose name starts with 'Ax' (AxClass, AxView, …)."""
    return path.is_dir() and path.name.startswith("Ax")


def _has_xml(path: Path) -> bool:
    return next(path.glob("*.xml"), None) is not None


def _fts5_available() -> bool:
    with closing(sqlite3.connect(":memory:")) as conn:
        try:
            conn.execute("CREATE VIRTUAL TABLE _probe USING fts5(x)")
            return True
        except sqlite3.OperationalError:
            return False


FTS5_AVAILABLE = _fts5_available()


class D365Index:
    """A SQLite-backed symbolic index. Open once, query many times.

    Use as a context manager or call :meth:`close` explicitly.
    """

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.fts = FTS5_AVAILABLE
        self._ensure_schema()

    # -- lifecycle -----------------------------------------------------------------

    def __enter__(self) -> "D365Index":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self.conn.close()

    def _ensure_schema(self) -> None:
        cur = self.conn
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS artifacts (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                artifact_type TEXT NOT NULL,
                model TEXT,
                package TEXT,
                classification TEXT,
                relative_path TEXT,
                label TEXT,
                is_public INTEGER DEFAULT 0,
                data_management_enabled INTEGER DEFAULT 0,
                public_entity_name TEXT,
                public_collection_name TEXT,
                source TEXT NOT NULL DEFAULT 'custom'
            )
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_artifacts_name ON artifacts(name)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_artifacts_name_nocase ON artifacts(name COLLATE NOCASE)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_artifacts_type ON artifacts(artifact_type)")
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS relations (
                id INTEGER PRIMARY KEY,
                relation_type TEXT NOT NULL,
                source TEXT NOT NULL,
                target TEXT NOT NULL,
                model TEXT,
                relative_path TEXT
            )
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_relations_source ON relations(source)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_relations_target ON relations(target)")
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS indexed_packages (
                package TEXT PRIMARY KEY,
                artifact_count INTEGER,
                source TEXT
            )
            """
        )
        cur.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
        cur.execute(
            "INSERT OR IGNORE INTO meta(key, value) VALUES('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )
        if self.fts:
            # External-content FTS5 mirror of `artifacts`; rebuilt in one shot after load.
            cur.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS artifacts_fts USING fts5(
                    name, label, relative_path, artifact_type, package,
                    content='artifacts', content_rowid='id', tokenize='unicode61'
                )
                """
            )
        self.conn.commit()

    # -- build ---------------------------------------------------------------------

    def build_from_catalog(self, catalog: Catalog, *, source: str = "custom") -> dict[str, int]:
        """Load a parsed :class:`Catalog` (rich: labels, flags, relations) into the index."""
        cur = self.conn
        cur.execute("DELETE FROM artifacts WHERE source = ?", (source,))
        cur.executemany(
            """
            INSERT INTO artifacts
                (name, artifact_type, model, package, classification, relative_path, label,
                 is_public, data_management_enabled, public_entity_name, public_collection_name, source)
            VALUES (:name, :artifact_type, :model, :package, :classification, :relative_path, :label,
                    :is_public, :data_management_enabled, :public_entity_name, :public_collection_name, :source)
            """,
            [self._artifact_row(artifact, source) for artifact in catalog.artifacts],
        )
        # Relations are corpus-wide; for the custom source we replace them wholesale.
        if source == "custom":
            cur.execute("DELETE FROM relations")
            cur.executemany(
                """
                INSERT INTO relations (relation_type, source, target, model, relative_path)
                VALUES (:relation_type, :source, :target, :model, :relative_path)
                """,
                [asdict(relation) for relation in catalog.relations],
            )
        self._record_packages(catalog.artifacts, source)
        self._rebuild_fts()
        self.conn.commit()
        return self.stats()

    def index_packages_local(
        self,
        packages_root: str | Path,
        *,
        progress: "callable[[str, int], None] | None" = None,
        only_missing: bool = True,
        batch_size: int = 5000,
        exclude_packages: "Iterable[str] | None" = None,
    ) -> dict[str, int]:
        """Path-based scan of a ``PackagesLocalDirectory`` tree (the standard D365 corpus).

        We do NOT parse every XML — for the standard corpus the element name is the file
        stem and the type is the parent folder, so a path walk yields a complete
        "does class X exist, in which package" symbol index very cheaply. Resumable: a
        package already present in ``indexed_packages`` is skipped when ``only_missing``.
        ``exclude_packages`` takes fnmatch patterns (e.g. ``BAB*``) so a publishable
        standard index can leave out custom/ISV packages deployed in the same PLD.
        """
        packages_root = Path(packages_root)
        already = self._indexed_package_names() if only_missing else set()
        excluded = list(exclude_packages or [])
        package_dirs = sorted(p for p in packages_root.iterdir() if p.is_dir()) if packages_root.exists() else []
        total = 0
        for package_dir in package_dirs:
            package = package_dir.name
            if package in already:
                continue
            if any(fnmatch.fnmatchcase(package, pattern) for pattern in excluded):
                continue
            rows = list(self._scan_standard_package(package_dir, package))
            if not rows:
                continue
            for start in range(0, len(rows), batch_size):
                self.conn.executemany(
                    """
                    INSERT INTO artifacts
                        (name, artifact_type, model, package, classification, relative_path, source)
                    VALUES (:name, :artifact_type, :model, :package, :classification, :relative_path, :source)
                    """,
                    rows[start : start + batch_size],
                )
            self.conn.execute(
                "INSERT OR REPLACE INTO indexed_packages(package, artifact_count, source) VALUES (?, ?, 'standard')",
                (package, len(rows)),
            )
            self.conn.commit()
            total += len(rows)
            if progress:
                progress(package, len(rows))
        self._rebuild_fts()
        self.conn.commit()
        return {"packages_indexed": len(package_dirs) - len(already), "artifacts_added": total}

    def _scan_standard_package(self, package_dir: Path, package: str) -> Iterator[dict[str, object]]:
        # Layout is PackagesLocalDirectory/<Package>/<Model>/<AxType>/<Name>.xml.
        # A package can hold MANY models (e.g. ApplicationSuite -> Foundation, ...), and the
        # model dir name is usually but NOT always the package name, so we enumerate model
        # dirs explicitly rather than assuming model == package.
        path_root = package_dir.parent  # so relative paths are resolvable from this root
        if not package_dir.is_dir():
            return
        for child in package_dir.iterdir():
            if not child.is_dir() or child.name in _NON_AOT_DIRS:
                continue
            if _is_aot_type_dir(child) and _has_xml(child):
                # Degenerate single-level layout: <Package>/<AxType>/<Name>.xml
                yield from self._scan_type_dir(child, package, package, path_root)
            else:
                # Model dir: <Package>/<Model>/<AxType>/... — index every Ax* type folder.
                model = child.name
                for type_dir in child.iterdir():
                    if _is_aot_type_dir(type_dir):
                        yield from self._scan_type_dir(type_dir, package, model, path_root)

    @staticmethod
    def _scan_type_dir(type_dir: Path, package: str, model: str, path_root: Path) -> Iterator[dict[str, object]]:
        artifact_type = type_dir.name
        for xml_file in type_dir.glob("*.xml"):
            try:
                rel = str(xml_file.relative_to(path_root)).replace("\\", "/")
            except ValueError:
                rel = str(xml_file).replace("\\", "/")
            yield {
                "name": xml_file.stem,
                "artifact_type": artifact_type,
                "model": model,
                "package": package,
                "classification": "standard-reference",
                "relative_path": rel,
                "source": "standard",
            }

    # -- query ---------------------------------------------------------------------

    def exists(self, name: str, artifact_type: str | None = None) -> bool:
        """The anti-hallucination primitive: does this AOT element actually exist?"""
        if artifact_type:
            row = self.conn.execute(
                "SELECT 1 FROM artifacts WHERE name = ? COLLATE NOCASE AND artifact_type = ? LIMIT 1",
                (name, artifact_type),
            ).fetchone()
        else:
            row = self.conn.execute(
                "SELECT 1 FROM artifacts WHERE name = ? COLLATE NOCASE LIMIT 1", (name,)
            ).fetchone()
        return row is not None

    def lookup_exact(self, name: str, artifact_type: str | None = None, limit: int = 25) -> list[dict[str, object]]:
        sql = "SELECT * FROM artifacts WHERE name = ? COLLATE NOCASE"
        params: list[object] = [name]
        if artifact_type:
            sql += " AND artifact_type = ?"
            params.append(artifact_type)
        sql += " ORDER BY (source='custom') DESC, name LIMIT ?"
        params.append(limit)
        return [self._row_to_dict(r) for r in self.conn.execute(sql, params).fetchall()]

    def search(self, query: str, *, artifact_type: str | None = None, limit: int = 20) -> list[dict[str, object]]:
        """Full-text/prefix search over names, labels, paths. Custom corpus ranks first."""
        match = _to_fts_query(query)
        if self.fts and match:
            sql = (
                "SELECT a.* FROM artifacts_fts f JOIN artifacts a ON a.id = f.rowid "
                "WHERE artifacts_fts MATCH ?"
            )
            params: list[object] = [match]
            if artifact_type:
                sql += " AND a.artifact_type = ?"
                params.append(artifact_type)
            sql += " ORDER BY (a.source='custom') DESC, rank LIMIT ?"
            params.append(limit)
            try:
                return [self._row_to_dict(r) for r in self.conn.execute(sql, params).fetchall()]
            except sqlite3.OperationalError:
                pass  # malformed MATCH -> fall back to LIKE
        return self._search_like(query, artifact_type, limit)

    def _search_like(self, query: str, artifact_type: str | None, limit: int) -> list[dict[str, object]]:
        like = f"%{query.strip()}%"
        sql = "SELECT * FROM artifacts WHERE (name LIKE ? OR label LIKE ? OR relative_path LIKE ?)"
        params: list[object] = [like, like, like]
        if artifact_type:
            sql += " AND artifact_type = ?"
            params.append(artifact_type)
        sql += " ORDER BY (source='custom') DESC, name LIMIT ?"
        params.append(limit)
        return [self._row_to_dict(r) for r in self.conn.execute(sql, params).fetchall()]

    def relations_of(self, name: str, *, limit: int = 200) -> list[dict[str, object]]:
        rows = self.conn.execute(
            "SELECT relation_type, source, target, model, relative_path FROM relations "
            "WHERE source = ? OR target = ? LIMIT ?",
            (name, name, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def neighbors(self, name: str, *, limit: int = 50) -> list[str]:
        rows = self.conn.execute(
            "SELECT source, target FROM relations WHERE source = ? OR target = ? LIMIT ?",
            (name, name, limit * 2),
        ).fetchall()
        seen: list[str] = []
        for r in rows:
            for candidate in (r["source"], r["target"]):
                if candidate and candidate != name and candidate not in seen:
                    seen.append(candidate)
        return seen[:limit]

    def stats(self) -> dict[str, int]:
        total = self.conn.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0]
        custom = self.conn.execute("SELECT COUNT(*) FROM artifacts WHERE source='custom'").fetchone()[0]
        standard = self.conn.execute("SELECT COUNT(*) FROM artifacts WHERE source='standard'").fetchone()[0]
        relations = self.conn.execute("SELECT COUNT(*) FROM relations").fetchone()[0]
        packages = self.conn.execute("SELECT COUNT(*) FROM indexed_packages").fetchone()[0]
        return {
            "artifacts_total": total,
            "artifacts_custom": custom,
            "artifacts_standard": standard,
            "relations": relations,
            "packages_indexed": packages,
            "fts5": int(self.fts),
        }

    def sample_by_type(self, artifact_type: str, *, custom_first: bool = True, limit: int = 5) -> list[dict[str, object]]:
        """Return example artifacts of one AOT type (custom first), for scaffolding a new object."""
        order = "(source='custom') DESC, " if custom_first else ""
        sql = f"SELECT * FROM artifacts WHERE artifact_type = ? COLLATE NOCASE ORDER BY {order}name LIMIT ?"
        return [self._row_to_dict(r) for r in self.conn.execute(sql, (artifact_type, limit)).fetchall()]

    def paths_by_type(self, artifact_type: str, *, limit: int = 200) -> list[tuple[str, str]]:
        """Sample (relative_path, source) for one AOT type — used to learn its structural profile."""
        rows = self.conn.execute(
            "SELECT relative_path, source FROM artifacts WHERE artifact_type = ? AND relative_path IS NOT NULL LIMIT ?",
            (artifact_type, limit),
        ).fetchall()
        return [(r["relative_path"], r["source"]) for r in rows]

    def list_types(self) -> list[dict[str, object]]:
        """Every AOT object type the index covers, with counts — the universe the agent can be
        grounded on. Use to answer 'what kinds of objects can you help with?'."""
        return self.counts_by_type(limit=10_000)

    def counts_by_type(self, *, source: str | None = None, limit: int = 40) -> list[dict[str, object]]:
        sql = "SELECT artifact_type, COUNT(*) AS n FROM artifacts"
        params: list[object] = []
        if source:
            sql += " WHERE source = ?"
            params.append(source)
        sql += " GROUP BY artifact_type ORDER BY n DESC LIMIT ?"
        params.append(limit)
        return [dict(r) for r in self.conn.execute(sql, params).fetchall()]

    # -- helpers -------------------------------------------------------------------

    def _rebuild_fts(self) -> None:
        if self.fts:
            self.conn.execute("INSERT INTO artifacts_fts(artifacts_fts) VALUES('rebuild')")

    def _record_packages(self, artifacts: Iterable[Artifact], source: str) -> None:
        counts: dict[str, int] = {}
        for artifact in artifacts:
            counts[artifact.package or artifact.model or "?"] = counts.get(artifact.package or artifact.model or "?", 0) + 1
        for package, count in counts.items():
            self.conn.execute(
                "INSERT OR REPLACE INTO indexed_packages(package, artifact_count, source) VALUES (?, ?, ?)",
                (package, count, source),
            )

    def _indexed_package_names(self) -> set[str]:
        return {r[0] for r in self.conn.execute("SELECT package FROM indexed_packages").fetchall()}

    @staticmethod
    def _artifact_row(artifact: Artifact, source: str) -> dict[str, object]:
        row = asdict(artifact)
        row["is_public"] = int(bool(artifact.is_public))
        row["data_management_enabled"] = int(bool(artifact.data_management_enabled))
        row["source"] = source
        return row

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict[str, object]:
        data = dict(row)
        data.pop("id", None)
        if "is_public" in data:
            data["is_public"] = bool(data["is_public"])
        if "data_management_enabled" in data:
            data["data_management_enabled"] = bool(data["data_management_enabled"])
        return data


def _to_fts_query(query: str) -> str:
    """Turn free text into a safe FTS5 prefix query: each alnum token -> "token"* joined by OR.

    Quoting each token as a string literal neutralises FTS5 operators in user input.
    """
    import re

    tokens = re.findall(r"[A-Za-z0-9_]+", query or "")
    if not tokens:
        return ""
    return " OR ".join(f'"{token}"*' for token in tokens)


def build_index_file(
    db_path: str | Path,
    catalog: Catalog | None = None,
    *,
    packages_root: str | Path | None = None,
    rebuild: bool = False,
    progress: "callable[[str, int], None] | None" = None,
    exclude_packages: Iterable[str] | None = None,
) -> dict[str, int]:
    """Convenience builder used by the CLI: (re)build a DB from a catalog and/or packages-local."""
    db_path = Path(db_path)
    if rebuild and db_path.exists():
        db_path.unlink()
    with D365Index(db_path) as index:
        if catalog is not None:
            index.build_from_catalog(catalog, source="custom")
        if packages_root is not None:
            index.index_packages_local(packages_root, progress=progress, exclude_packages=exclude_packages)
        return index.stats()
