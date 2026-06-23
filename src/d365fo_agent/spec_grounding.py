# src/d365fo_agent/spec_grounding.py
"""Anti-hallucination helpers for grounded Functional Design Documents (FDD).

Parses the two inline grounding tags defined in the Feature 2 tag contract:

    ✅ [VÉRIFIÉ: <tool-or-source>]   — claim verified against an MCP tool or doc chunk
    🔶 [JUGEMENT — à confirmer]      — functional reasoning from model judgment; unverified

Provides:
* ``parse_grounding_tags(markdown)``   → list[Claim] (all tagged spans, in document order)
* ``build_grounding_registry(claims)`` → list[dict]  (verified claims only → appendix rows)
* ``find_unverified_claims(markdown)`` → list[dict]  (judgment tags + heuristic bare facts)
* ``validate_fdd(markdown, *, required_sections)`` → dict report

Standard library only (``re``, ``dataclasses``). No file I/O.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Tag regexes — LOCKED syntax (see plan §tag-syntax)
# ---------------------------------------------------------------------------

_RE_VERIFIED = re.compile(r"✅\s*\[VÉRIFIÉ:\s*([^\]]+)\]")
_RE_JUDGMENT = re.compile(r"🔶\s*\[JUGEMENT\s*[—\-]\s*à\s*confirmer\]")

# Heuristic: factual-looking sentences that reference a named table or entity but
# carry no grounding tag.  Pattern: "la table XxxYyy" or "table XxxYyy" (CamelCase name).
_RE_BARE_TABLE = re.compile(
    r"\bla\s+table\b[^.!?\n]*\b([A-Z][A-Za-z0-9]{3,})\b[^.!?\n]*[.!?]?",
    re.IGNORECASE,
)


@dataclass
class Claim:
    """One grounding tag occurrence in a Markdown document."""

    kind: str          # "verified" | "judgment"
    source: str        # tool/source name (verified only; "" for judgment)
    line: int          # 1-based line number of the tag
    snippet: str       # the surrounding line text (trimmed to 120 chars)


def parse_grounding_tags(markdown: str) -> list[Claim]:
    """Return all ✅ and 🔶 tags found in ``markdown``, in document order.

    Each ``Claim`` records its kind, source (verified only), 1-based line number,
    and a trimmed snippet of the surrounding line for human review.
    """
    claims: list[Claim] = []
    for lineno, line in enumerate(markdown.splitlines(), start=1):
        for m in _RE_VERIFIED.finditer(line):
            claims.append(Claim(
                kind="verified",
                source=m.group(1).strip(),
                line=lineno,
                snippet=line.strip()[:120],
            ))
        for _m in _RE_JUDGMENT.finditer(line):
            claims.append(Claim(
                kind="judgment",
                source="",
                line=lineno,
                snippet=line.strip()[:120],
            ))
    return claims


def build_grounding_registry(claims: list[Claim]) -> list[dict]:
    """Return the appendix registry rows: one entry per VERIFIED claim.

    Each row is a plain dict with keys ``kind``, ``source``, ``line``, ``snippet`` — ready to
    render as a Markdown table or JSON.  Judgment-only claims are excluded; use
    ``find_unverified_claims`` to surface them separately.
    """
    return [
        {"kind": c.kind, "source": c.source, "line": c.line, "snippet": c.snippet}
        for c in claims
        if c.kind == "verified"
    ]


def find_unverified_claims(markdown: str) -> list[dict]:
    """Surface claims that need further grounding:

    1. Every 🔶 judgment tag (explicitly unverified by the author).
    2. Sentences that LOOK factual (heuristic: reference a CamelCase table/entity name with
       "la table" / "table" prefix) but carry no ✅ tag on the same line.

    Returns a list of dicts with keys ``kind`` ("judgment" | "heuristic"), ``line``, ``text``.
    The heuristic is intentionally conservative — it fires only on the ``la table XxxYyy``
    pattern so it doesn't flood the report on narrative prose.
    """
    issues: list[dict] = []
    for lineno, line in enumerate(markdown.splitlines(), start=1):
        stripped = line.strip()
        # 1. Explicit judgment tags.
        for _ in _RE_JUDGMENT.finditer(line):
            issues.append({"kind": "judgment", "line": lineno, "text": stripped[:120]})
        # 2. Bare table heuristic — only if the line has no ✅ tag and is not a
        #    Markdown table row (lines starting with "|" are registry/appendix rows,
        #    not factual prose claims).
        if (
            not _RE_VERIFIED.search(line)
            and not stripped.startswith("|")
            and _RE_BARE_TABLE.search(line)
        ):
            issues.append({"kind": "heuristic", "line": lineno, "text": stripped[:120]})
    return issues


# ---------------------------------------------------------------------------
# FDD section validator
# ---------------------------------------------------------------------------

_RE_H2 = re.compile(r"^##\s+(.+)$", re.MULTILINE)


def validate_fdd(
    markdown: str,
    *,
    required_sections: list[str] | None = None,
) -> dict:
    """Check that the FDD Markdown contains all required sections and a grounding appendix.

    ``required_sections`` is a list of section-title substrings (case-insensitive).  The
    default mirrors the locked FDD template (design §6).

    Returns a dict:
    ``{"ok": bool, "missing_sections": list[str], "has_grounding_appendix": bool,
       "verified_count": int, "judgment_count": int, "unverified_issues": int}``
    """
    if required_sections is None:
        required_sections = _DEFAULT_REQUIRED_SECTIONS

    found_headers = [m.group(1).strip().lower() for m in _RE_H2.finditer(markdown)]

    missing: list[str] = []
    for req in required_sections:
        req_lower = req.lower()
        if not any(req_lower in h for h in found_headers):
            missing.append(req)

    has_appendix = any(
        ("registre" in h and "grounding" in h) or "grounding" in h
        for h in found_headers
    )

    claims = parse_grounding_tags(markdown)
    verified = sum(1 for c in claims if c.kind == "verified")
    judgments = sum(1 for c in claims if c.kind == "judgment")
    issues = find_unverified_claims(markdown)

    return {
        "ok": len(missing) == 0 and has_appendix,
        "missing_sections": missing,
        "has_grounding_appendix": has_appendix,
        "verified_count": verified,
        "judgment_count": judgments,
        "unverified_issues": len(issues),
    }


_DEFAULT_REQUIRED_SECTIONS: list[str] = [
    "contexte",
    "périmètre",
    "processus métier",
    "exigences",
    "fit-gap",
    "conception fonctionnelle",
    "objets aot",
    "modèle de données",
    "sécurité",
    "intégrations",
    "états",
    "hypothèses",
    "registre de grounding",
]
