"""Learn each AOT type's structural shape from the corpus, so ``validate_xml`` can check ANY of the
indexed object types — not just the ~18 with hand-written rules.

For every root element we sample real examples and record which direct children are near-universal
(``required``) vs merely common (``recommended``). This is the corpus-driven counterpart to the
hand-curated ``ROOT_RULES`` in :mod:`d365fo_agent.validate`: curated rules stay authoritative for
the types they cover (hand-verified); the learned profile fills the long tail (AxView, AxKPI,
AxWorkflowApproval, AxEnumExtension, …) so generation of *any* object type can be structurally
verified. Built offline (like the index); ``validate_xml`` consumes the JSON and degrades to the
curated/generic rules when it is absent — never a hard dependency.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from xml.etree import ElementTree as ET

REQUIRED_FREQ = 0.95       # present in ~all examples -> structurally required
RECOMMENDED_FREQ = 0.40    # present in many examples -> recommended
DEFAULT_SAMPLE_PER_TYPE = 200
MIN_SAMPLE_FOR_REQUIRED = 5  # too few examples -> never call a child "required" (weak evidence)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _resolve(relative_path: str | None, roots: list[Path]) -> Path | None:
    if not relative_path:
        return None
    rel = relative_path.replace("\\", "/")
    for root in roots:
        candidate = root / rel
        if candidate.exists():
            return candidate
    return None


def build_type_profiles(
    index: object,
    roots: list[str | Path],
    *,
    sample_per_type: int = DEFAULT_SAMPLE_PER_TYPE,
    required_freq: float = REQUIRED_FREQ,
    recommended_freq: float = RECOMMENDED_FREQ,
    progress: "callable[[str, int], None] | None" = None,
) -> dict[str, dict[str, object]]:
    """Profile every AOT type the index knows. Returns ``{root_local: {artifact_type, required,
    recommended, known, sample_size}}`` keyed by the actual root element name."""
    resolved_roots = [Path(r) for r in roots]
    profiles: dict[str, dict[str, object]] = {}
    for type_row in index.list_types():  # type: ignore[attr-defined]
        artifact_type = str(type_row["artifact_type"])
        child_counts: Counter[str] = Counter()
        root_local: str | None = None
        sampled = 0
        for rel, _source in index.paths_by_type(artifact_type, limit=sample_per_type):  # type: ignore[attr-defined]
            path = _resolve(rel, resolved_roots)
            if path is None:
                continue
            try:
                root = ET.fromstring(path.read_text(encoding="utf-8", errors="ignore"))
            except ET.ParseError:
                continue
            sampled += 1
            if root_local is None:
                root_local = _local(root.tag)
            for child_name in {_local(child.tag) for child in root}:  # distinct direct children
                child_counts[child_name] += 1
        if sampled == 0 or root_local is None:
            continue
        required: list[str] = []
        recommended: list[str] = []
        for name, count in child_counts.items():
            freq = count / sampled
            if sampled >= MIN_SAMPLE_FOR_REQUIRED and freq >= required_freq:
                required.append(name)
            elif freq >= recommended_freq:
                recommended.append(name)
        profiles[root_local] = {
            "artifact_type": artifact_type,
            "required": sorted(required),
            "recommended": sorted(name for name in recommended if name not in required),
            "known": sorted(child_counts),
            "sample_size": sampled,
        }
        if progress:
            progress(root_local, sampled)
    return profiles


def save_type_profiles(profiles: dict[str, dict[str, object]], path: str | Path) -> str:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(profiles, indent=2, ensure_ascii=False), encoding="utf-8")
    return str(path)


def load_type_profiles(path: str | Path) -> dict[str, dict[str, object]] | None:
    path = Path(path)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def default_profiles_path(db_path: str | Path) -> Path:
    """The profile JSON lives next to the index DB (``…/aot-type-profiles.json``)."""
    return Path(db_path).parent / "aot-type-profiles.json"
