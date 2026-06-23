"""Download a prebuilt vector asset and merge ``chunk_vectors`` rows into an existing docs.db.

Mirrors ``knowledge_fetch.fetch_knowledge`` — stdlib only (``urllib``, ``gzip``, ``shutil``,
``sqlite3``).  Only http(s) URLs are accepted.  ``.gz`` assets are decompressed on the fly.

The asset is a SQLite file containing at minimum a ``chunk_vectors`` table with the same
schema as ``doc_store.DocIndex`` (``chunk_id, model, dim, vector BLOB``).  Rows are merged
with ``INSERT OR IGNORE`` so the operation is idempotent.
"""

from __future__ import annotations

import gzip
import shutil
import sqlite3
import tempfile
import urllib.request
from pathlib import Path

DEFAULT_DOC_VECTORS_URL: str | None = None  # Set when a prebuilt asset is published.


def _is_gzip(path: Path) -> bool:
    with open(path, "rb") as fh:
        return fh.read(2) == b"\x1f\x8b"


def fetch_doc_vectors(
    url: str | None = None,
    dest_db: str | Path | None = None,
    *,
    force: bool = False,
    opener=urllib.request.urlopen,
) -> dict[str, object]:
    """Download a prebuilt vector asset and merge its ``chunk_vectors`` into ``dest_db``.

    Parameters
    ----------
    url:
        The http(s) URL to the asset ``.db`` or ``.db.gz``.  Defaults to
        ``DEFAULT_DOC_VECTORS_URL`` (currently unset — pass ``--url`` explicitly).
    dest_db:
        Path to the existing ``docs.db`` to merge into.  Required.
    force:
        Re-download even if the temp file already exists (always re-merges).
    opener:
        Injectable for testing (replaces ``urllib.request.urlopen``).

    Returns a result dict with ``ok`` (bool) and relevant metadata or ``error``.
    """
    effective_url = url or DEFAULT_DOC_VECTORS_URL
    if not effective_url:
        return {
            "ok": False,
            "error": (
                "No vector asset URL configured.  Pass --url <asset .db/.db.gz>, "
                "or build your own with: d365fo-agent build-doc-index --embed."
            ),
        }
    if not (effective_url.startswith("http://") or effective_url.startswith("https://")):
        return {"ok": False, "error": f"Refusing non-http(s) URL: {effective_url}"}

    if dest_db is None:
        return {"ok": False, "error": "dest_db is required."}
    dest_db = Path(dest_db)
    if not dest_db.exists():
        return {"ok": False, "error": f"Destination docs.db not found: {dest_db}"}

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_raw = Path(tmp_dir) / "vectors.part"
        tmp_db = Path(tmp_dir) / "vectors.db"

        # Download.
        with opener(effective_url) as response, open(tmp_raw, "wb") as out:  # noqa: S310
            shutil.copyfileobj(response, out)

        # Decompress if needed.
        if effective_url.endswith(".gz") or _is_gzip(tmp_raw):
            with gzip.open(tmp_raw, "rb") as gz, open(tmp_db, "wb") as out:
                shutil.copyfileobj(gz, out)
        else:
            shutil.copy(tmp_raw, tmp_db)

        # Merge chunk_vectors rows into dest_db.
        src = sqlite3.connect(str(tmp_db))
        dst = sqlite3.connect(str(dest_db))
        try:
            dst.execute(
                "CREATE TABLE IF NOT EXISTS chunk_vectors "
                "(chunk_id INTEGER, model TEXT, dim INTEGER, vector BLOB)"
            )
            # Add unique index to make INSERT OR IGNORE work correctly per (chunk_id, model).
            dst.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_cv_id_model "
                "ON chunk_vectors(chunk_id, model)"
            )
            rows = src.execute(
                "SELECT chunk_id, model, dim, vector FROM chunk_vectors"
            ).fetchall()
            dst.executemany(
                "INSERT OR IGNORE INTO chunk_vectors(chunk_id, model, dim, vector) VALUES (?,?,?,?)",
                rows,
            )
            dst.commit()
            merged = len(rows)
        finally:
            src.close()
            dst.close()

    return {
        "ok": True,
        "dest": str(dest_db),
        "vectors_merged": merged,
        "source": effective_url,
    }
