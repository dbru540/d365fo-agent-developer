"""Queryable X++ development knowledge base: rules, syntax and logic per topic.

NOT a snippet library to copy-paste. Each topic encodes the LANGUAGE RULES, SYNTAX and LOGIC
needed to *write* correct X++ for D365 F&O (and, as the store grows, AX 2012) — so a coding
agent generates correct code from understanding, not from pasted templates. Every topic is:

* **grounded** — the AOT elements/types/APIs it references are exists-checked against the index
  (anti-hallucination); a topic that names something the corpus does not contain is flagged;
* **illustrated from the real corpus** — at query time a real example is pulled via the index
  (``find_similar_examples``), never invented;
* **platform-aware** — ``platform`` is ``d365fo`` | ``ax2012`` | ``both`` so one store serves
  both platforms and tools can filter (CoC exists in D365 F&O, not in AX 2012, etc.).

Topic files live in ``data/guidance/<id>.md``: a small ``---`` frontmatter block followed by
body sections (``## Syntaxe`` / ``## Règles`` / ``## Logique``). Standard library only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

_VALID_PLATFORMS = {"d365fo", "ax2012", "both"}
_LIST_KEYS = {"object_types", "grounds", "related_topics", "related_tools"}

# Kernel types/APIs that are REAL and valid but carry no AOT element XML, so they never appear in
# the symbol index (e.g. base enums NoYes/Gender). Referencing them is grounded, not hallucinated.
KERNEL_ALLOWLIST = frozenset({"NoYes", "NoYesId", "Gender", "Weekday", "Timezone"})


@dataclass
class Topic:
    id: str
    title: str = ""
    summary: str = ""
    platform: str = "d365fo"
    object_types: list[str] = field(default_factory=list)
    grounds: list[str] = field(default_factory=list)
    example_type: str | None = None
    example_query: str | None = None
    related_topics: list[str] = field(default_factory=list)
    related_tools: list[str] = field(default_factory=list)
    sections: dict[str, str] = field(default_factory=dict)


def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Split a topic file into (frontmatter dict, body). Frontmatter is a leading ``---`` block
    of ``key: value`` lines; list-valued keys are comma-split."""
    if not text.lstrip().startswith("---"):
        return {}, text
    stripped = text.lstrip()
    end = stripped.find("\n---", 3)
    if end == -1:
        return {}, text
    block = stripped[3:end].strip("\n")
    body = stripped[end + 4:].lstrip("\n")
    meta: dict[str, Any] = {}
    for line in block.splitlines():
        if not line.strip() or ":" not in line:
            continue
        key, _, value = line.partition(":")
        key, value = key.strip(), value.strip()
        if key in _LIST_KEYS:
            meta[key] = [v.strip() for v in value.split(",") if v.strip()]
        else:
            meta[key] = value
    return meta, body


def _parse_sections(body: str) -> dict[str, str]:
    """Body text split by ``## Header`` into {header_lower: content}."""
    sections: dict[str, str] = {}
    current = None
    buf: list[str] = []
    for line in body.splitlines():
        m = re.match(r"^##\s+(.*)$", line)
        if m:
            if current is not None:
                sections[current] = "\n".join(buf).strip()
            current = m.group(1).strip().lower()
            buf = []
        elif current is not None:
            buf.append(line)
    if current is not None:
        sections[current] = "\n".join(buf).strip()
    return sections


def load_guidance(guidance_dir: str | Path) -> dict[str, Topic]:
    """Load every ``*.md`` topic file under ``guidance_dir`` into a {id: Topic} map."""
    guidance_dir = Path(guidance_dir)
    topics: dict[str, Topic] = {}
    if not guidance_dir.is_dir():
        return topics
    for path in sorted(guidance_dir.glob("*.md")):
        meta, body = _parse_frontmatter(path.read_text(encoding="utf-8"))
        topic_id = str(meta.get("id") or path.stem)
        platform = str(meta.get("platform", "d365fo"))
        topics[topic_id] = Topic(
            id=topic_id,
            title=str(meta.get("title", topic_id)),
            summary=str(meta.get("summary", "")),
            platform=platform if platform in _VALID_PLATFORMS else "d365fo",
            object_types=list(meta.get("object_types", [])),
            grounds=list(meta.get("grounds", [])),
            example_type=meta.get("example_type") or None,
            example_query=meta.get("example_query") or None,
            related_topics=list(meta.get("related_topics", [])),
            related_tools=list(meta.get("related_tools", [])),
            sections=_parse_sections(body),
        )
    return topics


def _platform_matches(topic: Topic, platform: str | None) -> bool:
    if not platform:
        return True
    return topic.platform == platform or topic.platform == "both" or platform == "both"


def list_guidance(
    topics: dict[str, Topic], *, platform: str | None = None, object_type: str | None = None,
    type_profiles: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    out = []
    for t in topics.values():
        if not _platform_matches(t, platform):
            continue
        if object_type and object_type not in t.object_types:
            continue
        out.append({"id": t.id, "title": t.title, "summary": t.summary,
                    "platform": t.platform, "object_types": t.object_types, "kind": "guide"})
    # Long-tail: one structural reference per AOT type (d365fo, corpus-learned).
    if type_profiles and platform in (None, "d365fo", "both"):
        hand_types = {ot for t in topics.values() for ot in t.object_types}
        for entry in list_type_topics(type_profiles):
            if object_type and object_type != entry["id"]:
                continue
            # Don't shadow a rich hand-authored guide for the same type.
            if entry["id"] in hand_types and not object_type:
                pass
            out.append(entry)
    return sorted(out, key=lambda d: (d.get("kind") != "guide", d["id"]))


def get_guidance(
    topics: dict[str, Topic],
    topic_id: str,
    *,
    index: Any = None,
    ax_index: Any = None,
    roots: list[Path] | None = None,
    type_profiles: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Full topic: sections (syntax/rules/logic), grounding status, a real corpus example.

    Platform-routed: an ``ax2012`` topic grounds against ``ax_index``, otherwise against the
    D365 F&O ``index``. Without the relevant index the prose is still returned (degraded mode) —
    grounding is listed but not verified (``in_index`` is None) and no example is pulled.

    Long-tail fallback: when ``topic_id`` is not a hand-authored topic but names an AOT type known
    to ``type_profiles``, a corpus-learned structural reference for that type is synthesized.
    """
    topic = topics.get(topic_id)
    if topic is None:
        synth = synthesize_type_topic(topic_id, type_profiles, index=index, roots=roots)
        if synth is not None:
            return synth
        lower = topic_id.lower()
        suggestions = sorted(tid for tid in topics if lower in tid.lower() or tid.lower() in lower)
        suggestions += [e["id"] for e in list_type_topics(type_profiles)
                        if lower in e["id"].lower()][:5]
        return {"found": False, "topic": topic_id,
                "error": "unknown guidance topic", "suggestions": suggestions}

    index = ax_index if topic.platform == "ax2012" else index
    grounding = [
        {"name": name,
         "in_index": (None if index is None
                      else (index.exists(name) or name in KERNEL_ALLOWLIST)),
         "kernel": name in KERNEL_ALLOWLIST}
        for name in topic.grounds
    ]
    example = None
    if index is not None and topic.example_query:
        from d365fo_agent.knowledge import find_similar_examples

        result = find_similar_examples(index, topic.example_query, roots or [],
                                       artifact_type=topic.example_type, limit=1)
        examples = result.get("examples") or []
        if examples:
            top = examples[0]
            example = {"found": True, "name": top.get("name"),
                       "artifact_type": top.get("artifact_type"),
                       "model": top.get("model"), "relative_path": top.get("relative_path")}
        else:
            example = {"found": False}

    return {
        "found": True, "id": topic.id, "title": topic.title, "summary": topic.summary,
        "platform": topic.platform, "object_types": topic.object_types,
        "sections": topic.sections, "grounding": grounding, "example": example,
        "related_topics": topic.related_topics, "related_tools": topic.related_tools,
    }


def _topic_text(topic: Topic) -> str:
    return " ".join([topic.id.replace("-", " "), topic.title, topic.summary,
                     " ".join(topic.object_types), " ".join(topic.sections.values())]).lower()


def search_guidance(
    topics: dict[str, Topic], query: str, *, platform: str | None = None, limit: int = 5,
    type_profiles: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    terms = [t for t in re.split(r"\W+", query.lower()) if len(t) > 2]
    scored = []
    for t in topics.values():
        if not _platform_matches(t, platform):
            continue
        text = _topic_text(t)
        score = sum(text.count(term) for term in terms)
        # Title/summary hits weigh more — they are the topic's intent.
        head = (t.title + " " + t.summary).lower()
        score += 3 * sum(1 for term in terms if term in head)
        if score:
            scored.append((score, {"id": t.id, "title": t.title, "summary": t.summary,
                                   "platform": t.platform, "kind": "guide", "score": score}))
    # Long-tail type references match on the type name (e.g. "AxKPI", "workflow").
    if type_profiles and platform in (None, "d365fo", "both"):
        for entry in list_type_topics(type_profiles):
            name = entry["id"].lower()
            score = 4 * sum(1 for term in terms if term in name)
            if score:
                scored.append((score, {**entry, "score": score}))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [entry for _, entry in scored[:limit]]


def grounding_report(
    topics: dict[str, Topic], index: Any, *, allowlist: Iterable[str] = KERNEL_ALLOWLIST
) -> dict[str, list[str]]:
    """Per-topic list of referenced symbols absent from the index (anti-hallucination gate).

    An empty dict means every topic is fully grounded. ``allowlist`` covers kernel types/APIs that
    are real but carry no AOT element XML (base enums, intrinsics); defaults to KERNEL_ALLOWLIST."""
    allow = set(allowlist)
    report: dict[str, list[str]] = {}
    for topic in topics.values():
        missing = [name for name in topic.grounds
                   if name not in allow and not index.exists(name)]
        if missing:
            report[topic.id] = missing
    return report


def _find_profile(profiles: dict[str, Any] | None, name: str) -> dict[str, Any] | None:
    """Resolve a type profile by AOT type name, case-insensitive and Ax-prefix tolerant."""
    if not profiles:
        return None
    if name in profiles:
        return profiles[name]
    low = name.lower()
    wanted = {low, low if low.startswith("ax") else "ax" + low}
    for key, prof in profiles.items():
        if key.lower() in wanted:
            return prof
    return None


def synthesize_type_topic(
    ax_type: str, profiles: dict[str, Any] | None, *, index: Any = None, roots: list[Path] | None = None
) -> dict[str, Any] | None:
    """Build a corpus-learned structural reference for ANY AOT type from its learned profile.

    This is how the knowledge base covers the long tail of ~70 object types WITHOUT hand-authoring
    one file each: the structure (required/recommended child nodes) is derived from real corpus
    examples (the type profile), and a real example is pulled live. Grounded by construction.
    """
    prof = _find_profile(profiles, ax_type)
    if prof is None:
        return None
    t = str(prof.get("artifact_type", ax_type))
    required = prof.get("required", [])
    recommended = prof.get("recommended", [])
    sections = {
        "structure": ("Child nodes present in virtually every real " + t + ": "
                      + ", ".join(required) + "." if required
                      else "No near-universal child structure was learned for " + t + "."),
        "recommended": ("Commonly present (optional): " + ", ".join(recommended) + ".")
                       if recommended else "No additional commonly-present nodes.",
        "how to create": (
            "Do NOT hand-write the XML from memory. Clone a real one: scaffold_object(\"" + t + "\") "
            "copies a real corpus example, renamed, as your starting skeleton; fill it in, then "
            "validate_xml against the learned profile to confirm the required nodes are present. "
            "Use get_signature / find_similar_examples to study real instances first."),
    }
    example = None
    if index is not None:
        try:
            rows = index.sample_by_type(t, limit=1)
        except Exception:  # noqa: BLE001
            rows = []
        if rows:
            r = rows[0]
            example = {"found": True, "name": r.get("name"), "artifact_type": r.get("artifact_type"),
                       "model": r.get("model"), "relative_path": r.get("relative_path")}
        else:
            example = {"found": False}
    return {
        "found": True, "id": t, "title": f"{t} — object structure (corpus-learned)",
        "summary": f"Structural contract for {t}, learned from real corpus examples.",
        "platform": "d365fo", "object_types": [t], "kind": "type-reference",
        "sections": sections, "grounding": [], "example": example,
        "related_topics": [], "related_tools": ["scaffold_object", "validate_xml", "get_signature",
                                                "find_similar_examples"],
    }


def list_type_topics(profiles: dict[str, Any] | None) -> list[dict[str, Any]]:
    """One catalogue entry per AOT type known to the learned profiles (the long-tail coverage)."""
    if not profiles:
        return []
    out = []
    for prof in profiles.values():
        t = str(prof.get("artifact_type", ""))
        if not t:
            continue
        out.append({"id": t, "title": f"{t} — object structure (corpus-learned)",
                    "summary": f"Structural contract for {t}, learned from real corpus examples.",
                    "platform": "d365fo", "object_types": [t], "kind": "type-reference"})
    return sorted(out, key=lambda d: d["id"])


def default_guidance_dir() -> Path | None:
    """The bundled ``data/guidance`` directory (source tree in dev, package data once installed)."""
    candidates = []
    src = Path(__file__).resolve().parent / "data" / "guidance"
    candidates.append(src)
    try:
        from importlib.resources import files

        candidates.append(Path(str(files("d365fo_agent").joinpath("data", "guidance"))))
    except Exception:  # noqa: BLE001
        pass
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return None
