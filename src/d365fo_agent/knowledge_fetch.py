"""Download a prebuilt standard-D365 knowledge index into the local cache.

This is what lets the MCP server help with X++ development WITHOUT the user re-indexing a full
repo every time: the standard D365 corpus is the same for everyone, so it is indexed once and
published as a release asset. ``fetch-knowledge`` downloads it to ``~/.d365fo-agent/d365fo.db``
(a ``.gz`` asset is decompressed on the fly). The user's own custom code stays optional
(``--repo-root``). Standard-library only (``urllib`` + ``gzip``).
"""

from __future__ import annotations

import gzip
import shutil
import urllib.request
from pathlib import Path

# Published location of the standard-D365 knowledge index (a SQLite .db or .db.gz). The asset is
# decoupled from the code version (tag `knowledge-v1`) so wheel releases don't re-upload 100 MB.
# Override with --url, or build your own from a PLD when the asset is unavailable.
DEFAULT_KNOWLEDGE_URL = (
    "https://github.com/dbru540/d365fo-agent/releases/download/knowledge-v1/d365fo-standard.db.gz"
)


def _is_gzip(path: Path) -> bool:
    with open(path, "rb") as handle:
        return handle.read(2) == b"\x1f\x8b"


def fetch_knowledge(
    url: str | None = None,
    dest: str | Path | None = None,
    *,
    force: bool = False,
    opener=urllib.request.urlopen,
) -> dict[str, object]:
    """Download the knowledge index to ``dest`` (default: the local cache). Returns a result dict.

    ``opener`` is injectable for testing. Only http(s) URLs are accepted.
    """
    from d365fo_agent.mcp_server import default_knowledge_db

    dest = Path(dest) if dest else default_knowledge_db()
    url = url or DEFAULT_KNOWLEDGE_URL
    if not url:
        return {
            "ok": False,
            "error": "No knowledge URL configured. Pass --url <release asset .db/.db.gz>, or build "
                     "your own with: d365fo-agent build-index --db <out.db> --packages-root <your "
                     "D365 PackagesLocalDirectory> --rebuild",
        }
    if not (url.startswith("http://") or url.startswith("https://")):
        return {"ok": False, "error": f"Refusing non-http(s) URL: {url}"}
    if dest.exists() and not force:
        return {"ok": True, "skipped": True, "dest": str(dest),
                "note": "knowledge index already present (use --force to re-download)"}

    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    with opener(url) as response, open(tmp, "wb") as out:  # noqa: S310 - scheme checked above
        shutil.copyfileobj(response, out)

    if url.endswith(".gz") or _is_gzip(tmp):
        with gzip.open(tmp, "rb") as gz, open(dest, "wb") as out:
            shutil.copyfileobj(gz, out)
        tmp.unlink()
    else:
        tmp.replace(dest)

    return {"ok": True, "dest": str(dest), "bytes": dest.stat().st_size, "source": url}
