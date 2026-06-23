# Feature 2 — Functional-Specification Workflow/Skill: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a `SKILL.md` that lets an agent autonomously produce a grounded Functional Design Document (FDD) for a D365 F&O topic — every factual claim tagged inline, backed by a "registre de grounding" appendix — by orchestrating the EXISTING MCP tools plus the doc index from Phase 1. Add a small pure-Python helper module (`spec_grounding.py`) for tag parsing, registry building, and FDD validation; add a canonical FDD Markdown template; export to `.docx` via the existing `docx` skill.

**Architecture:** No new MCP tools are added. The skill is an agent-facing instruction file that drives the existing 27 tools in the correct orchestration order. The Python helper (`spec_grounding.py`) is testable pure logic (stdlib-only, matching project norm). The SKILL.md and FDD template are authored artefacts validated against an acceptance example.

**Tech Stack:** Python 3.11+, standard library only (`re`, `dataclasses`), `pytest`, Markdown. Skill location: `skills/functional-spec/SKILL.md` (no existing `skills/` directory in the repo — this plan creates it; the choice is documented in Task 3).

**Out of scope (own plan):** `embed.py`, `[semantic]` extra, `fetch-doc-vectors`, prebuilt vector asset — all deferred to Phase 2 semantic layer.

---

## File Structure

- **Create** `src/d365fo_agent/spec_grounding.py` — `Claim` dataclass + `parse_grounding_tags`, `build_grounding_registry`, `find_unverified_claims`, `validate_fdd`.
- **Create** `tests/test_spec_grounding.py` — full TDD unit tests for the above.
- **Create** `skills/functional-spec/SKILL.md` — agent-facing orchestration instruction (full content authored in Task 3).
- **Create** `skills/functional-spec/templates/fdd-template.md` — canonical FDD section skeleton with tag examples and grounding-appendix stub.
- **Modify** `README.md` and `docs/mcp-server.md` — reference the skill (Task 5).

Run all tests with: `$env:PYTHONPATH='src'; pytest -q` (PowerShell) — POSIX: `PYTHONPATH=src pytest -q`.

---

## Tag syntax (LOCKED — used in all tasks below)

The grounding tag contract formalises §7 of the design. Two inline tag forms:

```
✅ [VÉRIFIÉ: <tool>/<source>]
🔶 [JUGEMENT — à confirmer]
```

Regex (Python, compiled once):

```python
import re

# Verified tag:  ✅ [VÉRIFIÉ: SomeToolOrSource]
_RE_VERIFIED = re.compile(
    r"✅\s*\[VÉRIFIÉ:\s*([^\]]+)\]"
)

# Judgment tag:  🔶 [JUGEMENT — à confirmer]
_RE_JUDGMENT = re.compile(
    r"🔶\s*\[JUGEMENT\s*[—\-]\s*à\s*confirmer\]"
)
```

A "verified" claim's source field is the text captured by group 1 of `_RE_VERIFIED` (trimmed). It names either an MCP tool (e.g. `explore_functional_unit`, `get_sql_model`) or a doc citation (`search_docs/chunk-42 — url`).

---

## Task 1: `spec_grounding.py` — tag parsing, registry, unverified detection (`spec_grounding.py`)

**Files:**
- Create: `src/d365fo_agent/spec_grounding.py`
- Test: `tests/test_spec_grounding.py`

### Step 1: Write the failing test

```python
# tests/test_spec_grounding.py
"""Unit tests for spec_grounding — tag parsing, registry, unverified detection, FDD validation.

All inputs are synthetic Markdown strings; no file I/O needed. Standard library only.
"""

from d365fo_agent.spec_grounding import (
    Claim,
    build_grounding_registry,
    find_unverified_claims,
    parse_grounding_tags,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

VERIFIED_MD = (
    "Le module AP gère les factures fournisseurs. ✅ [VÉRIFIÉ: explore_functional_unit]\n"
    "La table VendTable contient les données maîtres. ✅ [VÉRIFIÉ: get_sql_model/VendTable]\n"
)

JUDGMENT_MD = (
    "Les approbations sont souvent configurées en 3 niveaux. 🔶 [JUGEMENT — à confirmer]\n"
)

MIXED_MD = VERIFIED_MD + JUDGMENT_MD + (
    "La sécurité est gérée par APs. ✅ [VÉRIFIÉ: get_security_links/AP]\n"
)

# A bare factual-looking sentence with no tag (should surface as unverified heuristic).
UNTAGGED_FACTUAL = "La table CustTable contient les données clients.\n"


# ---------------------------------------------------------------------------
# parse_grounding_tags
# ---------------------------------------------------------------------------


def test_parse_verified_tags():
    claims = parse_grounding_tags(VERIFIED_MD)
    assert len(claims) == 2
    assert all(c.kind == "verified" for c in claims)
    assert claims[0].source == "explore_functional_unit"
    assert claims[1].source == "get_sql_model/VendTable"


def test_parse_judgment_tags():
    claims = parse_grounding_tags(JUDGMENT_MD)
    assert len(claims) == 1
    assert claims[0].kind == "judgment"
    assert claims[0].source == ""


def test_parse_mixed_tags_order_preserved():
    claims = parse_grounding_tags(MIXED_MD)
    kinds = [c.kind for c in claims]
    assert kinds.count("verified") == 3
    assert kinds.count("judgment") == 1


def test_parse_no_tags_returns_empty():
    assert parse_grounding_tags("Aucun tag ici.\n") == []


def test_parse_claim_carries_line_number():
    md = "Ligne un.\nLe module AP. ✅ [VÉRIFIÉ: explore_functional_unit]\nLigne trois.\n"
    claims = parse_grounding_tags(md)
    assert claims[0].line == 2


# ---------------------------------------------------------------------------
# build_grounding_registry
# ---------------------------------------------------------------------------


def test_registry_contains_only_verified():
    claims = parse_grounding_tags(MIXED_MD)
    registry = build_grounding_registry(claims)
    assert all(r["kind"] == "verified" for r in registry)
    assert len(registry) == 3


def test_registry_entry_fields():
    claims = parse_grounding_tags(VERIFIED_MD)
    reg = build_grounding_registry(claims)
    entry = reg[0]
    assert "source" in entry and "line" in entry and "snippet" in entry
    assert entry["source"] == "explore_functional_unit"


def test_registry_empty_when_no_verified():
    claims = parse_grounding_tags(JUDGMENT_MD)
    assert build_grounding_registry(claims) == []


# ---------------------------------------------------------------------------
# find_unverified_claims
# ---------------------------------------------------------------------------


def test_find_unverified_includes_judgment_tags():
    issues = find_unverified_claims(JUDGMENT_MD)
    assert len(issues) >= 1
    assert any(i["kind"] == "judgment" for i in issues)


def test_find_unverified_includes_bare_table_references():
    """Heuristic: sentences containing 'table <Name>' or 'la table' with no following tag."""
    issues = find_unverified_claims(UNTAGGED_FACTUAL)
    assert len(issues) >= 1
    assert any("CustTable" in i["text"] or "table" in i["text"].lower() for i in issues)


def test_find_unverified_does_not_flag_verified_sentences():
    """A sentence ending with ✅ tag should NOT appear in find_unverified_claims."""
    issues = find_unverified_claims(VERIFIED_MD)
    # Lines that carry ✅ must not be in the issues list
    for issue in issues:
        assert "✅" not in issue["text"]


def test_find_unverified_empty_on_clean_doc():
    """No tags AND no heuristic pattern triggers → no issues."""
    clean = "Voici un commentaire général sans affirmation factuelle.\n"
    issues = find_unverified_claims(clean)
    assert issues == []
```

### Step 2: Run test to verify it fails

Run: `$env:PYTHONPATH='src'; pytest tests/test_spec_grounding.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'd365fo_agent.spec_grounding'`.

### Step 3: Write minimal implementation

```python
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
from dataclasses import dataclass, field

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
        # 2. Bare table heuristic — only if the line has no ✅ tag.
        if not _RE_VERIFIED.search(line) and _RE_BARE_TABLE.search(line):
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
```

### Step 4: Run test to verify it passes

Run: `$env:PYTHONPATH='src'; pytest tests/test_spec_grounding.py -q`
Expected: PASS (all tests pass).

### Step 5: Commit

```bash
git add src/d365fo_agent/spec_grounding.py tests/test_spec_grounding.py
git commit -m "feat: spec_grounding — tag parsing, registry, FDD validation (anti-hallucination)"
```

---

## Task 2: `validate_fdd` — FDD section validation tests + implementation

**Files:**
- Modify: `tests/test_spec_grounding.py` (append)
- `src/d365fo_agent/spec_grounding.py` already contains `validate_fdd`; this task adds its tests and confirms the full module is clean.

### Step 1: Write the failing tests (append to `tests/test_spec_grounding.py`)

```python
from d365fo_agent.spec_grounding import validate_fdd


# ---------------------------------------------------------------------------
# validate_fdd
# ---------------------------------------------------------------------------

_MINIMAL_FDD = """
## Contexte et objectif
Description du projet. ✅ [VÉRIFIÉ: explore_functional_unit]

## Périmètre
In: rapprochement. Out: paiements.

## Processus métier
As-is / to-be. 🔶 [JUGEMENT — à confirmer]

## Exigences
REQ-001: …

## Fit-Gap
Analyse. ✅ [VÉRIFIÉ: element_exists/VendSettlement]

## Conception fonctionnelle
Description.

## Objets AOT impactés
VendTable. ✅ [VÉRIFIÉ: find_relations/VendTable]

## Modèle de données
Schéma. ✅ [VÉRIFIÉ: get_sql_model/VendTable]

## Sécurité
Rôles. ✅ [VÉRIFIÉ: get_security_links/AP]

## Intégrations et OData
Aucune.

## États et reports
Aucun.

## Hypothèses et risques
À confirmer.

## Annexe : registre de grounding
| Ligne | Source | Snippet |
|---|---|---|
| 3 | explore_functional_unit | Description du projet. |
"""


def test_validate_fdd_ok_on_complete_doc():
    report = validate_fdd(_MINIMAL_FDD)
    assert report["ok"] is True
    assert report["missing_sections"] == []
    assert report["has_grounding_appendix"] is True
    assert report["verified_count"] >= 5
    assert report["judgment_count"] == 1


def test_validate_fdd_detects_missing_sections():
    no_security = _MINIMAL_FDD.replace("## Sécurité\nRôles. ✅ [VÉRIFIÉ: get_security_links/AP]\n", "")
    report = validate_fdd(no_security)
    assert report["ok"] is False
    assert any("sécurité" in s.lower() for s in report["missing_sections"])


def test_validate_fdd_detects_missing_appendix():
    no_appendix = _MINIMAL_FDD.replace("## Annexe : registre de grounding", "## Annexe : divers")
    report = validate_fdd(no_appendix)
    assert report["ok"] is False
    assert report["has_grounding_appendix"] is False


def test_validate_fdd_custom_required_sections():
    report = validate_fdd("## Contexte et objectif\n\nTexte.\n",
                          required_sections=["contexte"])
    # Missing appendix so ok=False, but missing_sections is empty.
    assert report["missing_sections"] == []
    assert report["has_grounding_appendix"] is False


def test_validate_fdd_counts_tags_correctly():
    md = (
        "✅ [VÉRIFIÉ: t1]\n"
        "✅ [VÉRIFIÉ: t2]\n"
        "🔶 [JUGEMENT — à confirmer]\n"
        "🔶 [JUGEMENT — à confirmer]\n"
        "🔶 [JUGEMENT — à confirmer]\n"
        "## Annexe : registre de grounding\n"
    )
    report = validate_fdd(md, required_sections=[])
    assert report["verified_count"] == 2
    assert report["judgment_count"] == 3
```

### Step 2: Run test to verify it fails

Run: `$env:PYTHONPATH='src'; pytest tests/test_spec_grounding.py::test_validate_fdd_ok_on_complete_doc -q`
Expected: FAIL if `validate_fdd` was not yet implemented; otherwise adjust any assertion gaps exposed.

### Step 3: No new implementation needed

`validate_fdd` and `_DEFAULT_REQUIRED_SECTIONS` were written in Task 1 Step 3. If tests fail, tune the section matching in `validate_fdd` (case-insensitive substring match already implemented). No structural changes to the module.

### Step 4: Run full spec_grounding suite

Run: `$env:PYTHONPATH='src'; pytest tests/test_spec_grounding.py -q`
Expected: all tests pass. Also lint: `ruff check src/d365fo_agent/spec_grounding.py`.

### Step 5: Commit

```bash
git add tests/test_spec_grounding.py
git commit -m "test: complete validate_fdd coverage in test_spec_grounding"
```

---

## Task 3: FDD Markdown template + SKILL.md

**Files:**
- Create: `skills/functional-spec/templates/fdd-template.md`
- Create: `skills/functional-spec/SKILL.md`

**Skill location decision:** No `skills/` or `.claude/skills/` directory exists in the repository. This plan creates `skills/functional-spec/` as the convention, co-located with the source tree. The `anthropic-skills:docx` skill is referenced by name — not re-implemented.

### Step 1: Create the FDD Markdown template

Create `skills/functional-spec/templates/fdd-template.md` with the following content (full, no placeholders):

```markdown
<!--
  FDD Template — D365 F&O Functional Design Document
  Skill: functional-spec | Version: 1.0 | Date: {{DATE}}
  Every factual claim MUST carry a grounding tag (see § Tag Contract below).
  ✅ [VÉRIFIÉ: <tool-or-source>]   = verified via MCP tool or doc chunk citation
  🔶 [JUGEMENT — à confirmer]      = model judgment — must be flagged for human review
-->

# Functional Design Document — {{TOPIC}}

**Date :** {{DATE}}
**Auteur :** {{AUTHOR}}
**Statut :** Brouillon

---

## Contexte et objectif

> Décrire le besoin métier, le périmètre du projet et les objectifs mesurables.

{{CONTEXTE}} ✅ [VÉRIFIÉ: explore_functional_unit]

---

## Périmètre

### Dans le périmètre

- {{IN_SCOPE_1}}

### Hors périmètre

- {{OUT_OF_SCOPE_1}}

---

## Processus métier

### As-is (situation actuelle)

{{AS_IS}} 🔶 [JUGEMENT — à confirmer]

### To-be (cible)

{{TO_BE}} 🔶 [JUGEMENT — à confirmer]

---

## Exigences

> Chaque exigence est numérotée et traçable vers le Fit-Gap.

| ID | Description | Priorité | Statut |
|---|---|---|---|
| REQ-001 | {{REQUIREMENT_1}} | Haute | Ouvert |

---

## Fit-Gap

> Pour chaque exigence, indiquer si le standard D365 couvre le besoin (Fit), nécessite une configuration (Config), ou un développement (Gap).

| REQ | Standard couvre ? | Source | Écart |
|---|---|---|---|
| REQ-001 | Fit ✅ [VÉRIFIÉ: element_exists/{{AOT_ELEMENT}}] | {{SOURCE}} | — |

---

## Conception fonctionnelle

> Description détaillée de la solution retenue, paramétrage, flux de données.

{{DESIGN}} 🔶 [JUGEMENT — à confirmer]

---

## Objets AOT impactés

> Tables, classes, formulaires, menus, énumérations, entités de données touchés.

| Objet | Type AOT | Opération | Source |
|---|---|---|---|
| {{TABLE_NAME}} | Table | Lire/Écrire | ✅ [VÉRIFIÉ: find_relations/{{TABLE_NAME}}] |

---

## Modèle de données

> Schéma des tables principales, clés primaires/étrangères, relations.

{{DATA_MODEL}} ✅ [VÉRIFIÉ: get_sql_model/{{TABLE_NAME}}]

---

## Sécurité

> Rôles, devoirs (duties) et privilèges impactés.

| Rôle / Devoir / Privilège | Action | Source |
|---|---|---|
| {{SECURITY_OBJECT}} | Accorder | ✅ [VÉRIFIÉ: get_security_links/{{MODULE}}] |

---

## Intégrations et OData

> Entités OData exposées, intégrations DMF, flux entrants/sortants.

{{INTEGRATIONS}} ✅ [VÉRIFIÉ: get_entity_exposure/{{ENTITY_NAME}}]

---

## États et reports

> SSRS, Power BI, rapports standards impactés.

{{REPORTS}} 🔶 [JUGEMENT — à confirmer]

---

## Hypothèses, risques et questions ouvertes

| # | Hypothèse / Risque | Statut | Responsable |
|---|---|---|---|
| H-01 | {{ASSUMPTION_1}} 🔶 [JUGEMENT — à confirmer] | Ouvert | — |

---

## Annexe : registre de grounding

> Ce registre est généré automatiquement depuis les tags ✅ du document.
> Chaque fait vérifié est tracé vers l'outil MCP ou le chunk documentaire source.

| Ligne | Source (outil / doc) | Extrait |
|---|---|---|
| _généré_ | _généré_ | _généré_ |
```

### Step 2: Create the SKILL.md

Create `skills/functional-spec/SKILL.md` with the following content (complete, no placeholders):

```markdown
---
name: functional-spec
description: >
  Produce a grounded Functional Design Document (FDD) for a D365 F&O topic.
  Orchestrates the existing MCP fact-tools in a defined order so every factual
  claim is verified against the AOT index or the documentation index before it
  is written into the FDD. Outputs Markdown (source of truth) plus optional
  .docx export via the docx skill.
when_to_use: >
  When a user asks to write, draft, or generate a functional specification,
  a functional design document, an FDD, or a "spécification fonctionnelle" for
  a D365 F&O module, process, or customisation. Also use when grounding an
  existing draft FDD against the AOT/doc index to surface unverified claims.
---

# Skill: functional-spec

## Purpose

Produce a **Functional Design Document (FDD)** for a D365 F&O topic that is:

- **Grounded** — every factual claim (table name, field, security object,
  OData entity, …) is verified via an MCP tool before it is written.
- **Transparent** — unverified functional reasoning is explicitly tagged
  `🔶 [JUGEMENT — à confirmer]` so reviewers know what still needs sign-off.
- **Auditable** — an appendix "registre de grounding" maps every ✅ tag to its
  tool call or document citation.

## Tag Contract (mandatory — read first)

Every factual claim in the FDD **must** carry one of two inline tags:

```
✅ [VÉRIFIÉ: <tool-or-source>]      ← verified via MCP tool or doc chunk
🔶 [JUGEMENT — à confirmer]         ← model judgment — mark and flag for human
```

**Rules:**
1. A claim is "verified" only if the information came from a tool response in
   this session or from a `search_docs`/`get_docs` doc chunk with a citation.
2. A claim is "judgment" if it comes from model training / general knowledge,
   even if plausible. Mark it — do not skip the tag.
3. The grounding appendix (last section) must be populated before the FDD is
   considered complete.
4. Never invent an AOT element name without first calling `element_exists`.

## Orchestration Order

Execute the following steps **in order**. Do not skip a step. If a tool call
returns "not found", record that honestly in the FDD (e.g. "élément absent de
l'index — vérification manuelle requise ✅ [VÉRIFIÉ: element_exists/<name>]").

### Step 1 — Domain exploration

```
explore_functional_unit(unit=<topic>, top=15)
```

- Records the core tables and entities for the functional unit.
- Tag every table/entity name listed: ✅ [VÉRIFIÉ: explore_functional_unit]
- Populate FDD sections: **Contexte et objectif**, **Périmètre**.

### Step 2 — Impacted objects

For each key table/entity identified in Step 1:

```
find_references(symbol=<table>)
find_reverse_references(symbol=<table>)
get_extension_chain(name=<table>)
```

(Use `find_relations(a=<tableA>, b=<tableB>)` only to relate TWO specific named objects — it is not a single-table lookup.)

- Builds the list of AOT objects impacted by the scope.
- Tag each confirmed object: ✅ [VÉRIFIÉ: find_references/<table>]
- Populate FDD section: **Objets AOT impactés**.

### Step 3 — Fit-Gap analysis

For each requirement and AOT element in scope:

```
element_exists(name=<element>)
get_entity_exposure(name=<entity>)
search_docs(query=<requirement description>, module=<module>)
```

- `element_exists` confirms the standard element is present (Fit) or absent
  (Gap). Tag: ✅ [VÉRIFIÉ: element_exists/<element>]
- `get_entity_exposure` confirms OData availability. Tag: ✅ [VÉRIFIÉ: get_entity_exposure/<entity>]
- `search_docs` finds MS Learn / internal spec passages that cover the
  requirement. Tag: ✅ [VÉRIFIÉ: search_docs/<chunk-id> — <source_ref>]
  Call `get_docs(chunk_id=<id>)` to read the full passage before citing it.
- Populate FDD section: **Fit-Gap**, **Intégrations et OData**.

### Step 4 — Security

```
get_security_links(name=<module-or-element>)
```

- Lists privileges, duties, and roles linked to the scope.
- Tag: ✅ [VÉRIFIÉ: get_security_links/<name>]
- Populate FDD section: **Sécurité**.

### Step 5 — Data model

For each key table:

```
get_sql_model(name=<table>)
```

- Returns SQL column names, types, and indexes — the source of truth for the
  data model section.
- Tag: ✅ [VÉRIFIÉ: get_sql_model/<table>]
- Populate FDD section: **Modèle de données**.

### Step 6 — Design rules

```
get_guidance(topic=<relevant-topic>)
```

- Retrieves X++ design rules relevant to the implementation (e.g. "chain-of-command",
  "data-entity", "security-wiring"). Call for each relevant topic.
- Tag: ✅ [VÉRIFIÉ: get_guidance/<topic>]
- Incorporate verified rules into: **Conception fonctionnelle**.

### Step 7 — Write the FDD

Using the template at `skills/functional-spec/templates/fdd-template.md`:

1. Fill every section with information gathered in Steps 1–6.
2. Tag every factual claim as ✅ or 🔶 — NO untagged factual sentences.
3. Mark all functional reasoning not backed by a tool call as
   🔶 [JUGEMENT — à confirmer].
4. Populate the **Annexe : registre de grounding** table from all ✅ tags
   (call `spec_grounding.build_grounding_registry` if running in a Python
   context, or build the table manually from your tag log).

### Step 8 — Validate

Before presenting the FDD to the user, verify it passes the built-in check:

```python
from d365fo_agent.spec_grounding import validate_fdd
report = validate_fdd(fdd_markdown)
# report["ok"] must be True; if False, fix missing sections or add appendix.
```

If `report["unverified_issues"] > 0`, review `find_unverified_claims(fdd_markdown)`
and either ground each issue with a tool call or downgrade it to a 🔶 tag.

### Step 9 — Export to .docx (optional)

Use the `anthropic-skills:docx` skill to convert the final Markdown to Word:

```
/anthropic-skills:docx  <path-to-fdd.md>
```

The Markdown file is the source of truth. The .docx is a distribution artefact.

## Grounding quality targets

| Metric | Target |
|---|---|
| Verified (✅) claims | ≥ 80 % of factual claims |
| Judgment (🔶) tags | Present on ALL unverified reasoning |
| Missing sections | 0 (all 13 template sections present) |
| Grounding appendix | Required — at least one row per ✅ tag |

## Tool reference summary

| Step | Tool | Purpose |
|---|---|---|
| 1 | `explore_functional_unit` | Domain tables/entities |
| 2 | `find_references` | Objects referencing the symbol (arg: `symbol`) |
| 2 | `find_reverse_references` | Reverse dependency map (arg: `symbol`) |
| 2 | `get_extension_chain` | Extension/CoC chain around an element (arg: `name`) |
| (opt) | `find_relations` | Relate TWO named tables/entities (args: `a`, `b`) |
| 3 | `element_exists` | Confirms AOT element is in the standard |
| 3 | `get_entity_exposure` | OData / DMF exposure |
| 3 | `search_docs` | Functional doc search (MS Learn + internal) |
| 3 | `get_docs` | Full doc chunk + citation |
| 4 | `get_security_links` | Privileges / duties / roles |
| 5 | `get_sql_model` | Table columns, types, indexes |
| 6 | `get_guidance` | Design rules (X++ / D365 patterns) |

## Failure modes to avoid

- **Do not invent element names.** Always call `element_exists` first.
- **Do not copy table schemas from memory.** Always call `get_sql_model`.
- **Do not write functional statements without a tag.** If you cannot ground
  it, tag it 🔶 — never leave it untagged.
- **Do not skip the grounding appendix.** `validate_fdd` will return `ok=False`
  without it.
- **Do not export .docx before the Markdown is validated** (`validate_fdd` ok).
```

### Step 3: Verify the files exist

```bash
ls skills/functional-spec/
ls skills/functional-spec/templates/
```

Expected: both `SKILL.md` and `templates/fdd-template.md` present.

### Step 4: Commit

```bash
git add skills/functional-spec/SKILL.md skills/functional-spec/templates/fdd-template.md
git commit -m "feat: functional-spec SKILL.md + FDD Markdown template"
```

---

## Task 4: Worked acceptance example

This task defines a synthetic acceptance check — a "mini-FDD" covering three tagged claims — that an implementer can run against `spec_grounding` to validate the module end-to-end. No new code files; the example is exercised via an inline pytest function appended to `tests/test_spec_grounding.py`.

### Step 1: Append the acceptance test (append to `tests/test_spec_grounding.py`)

```python
# ---------------------------------------------------------------------------
# Acceptance example — synthetic mini-FDD round-trip
# ---------------------------------------------------------------------------

_ACCEPTANCE_FDD = """\
## Contexte et objectif

Le module Accounts Payable (AP) gère les factures fournisseurs. ✅ [VÉRIFIÉ: explore_functional_unit]

## Périmètre

In: rapprochement factures/paiements. Out: comptabilisation des écarts.

## Processus métier

Les approbations sont souvent configurées en 3 niveaux de validation. 🔶 [JUGEMENT — à confirmer]

## Exigences

REQ-001: Le système doit rapprocher automatiquement les factures et les paiements.

## Fit-Gap

| REQ | Standard | Source | Écart |
|---|---|---|---|
| REQ-001 | Fit ✅ [VÉRIFIÉ: element_exists/VendSettlement] | VendSettlement | — |

## Conception fonctionnelle

La table VendTable contient les données maîtres fournisseurs. ✅ [VÉRIFIÉ: get_sql_model/VendTable]

## Objets AOT impactés

VendTable, VendTrans. ✅ [VÉRIFIÉ: find_relations/VendTable]

## Modèle de données

Colonnes: AccountNum, Name, Currency. ✅ [VÉRIFIÉ: get_sql_model/VendTable]

## Sécurité

Rôle AP Clerk. ✅ [VÉRIFIÉ: get_security_links/AP]

## Intégrations et OData

Entité VendorV2. ✅ [VÉRIFIÉ: get_entity_exposure/VendorV2]

## États et reports

Aucun état standard impacté. 🔶 [JUGEMENT — à confirmer]

## Hypothèses et risques

H-01: Le paramétrage des groupes de rapprochement est déjà en place. 🔶 [JUGEMENT — à confirmer]

## Annexe : registre de grounding

| Ligne | Source | Extrait |
|---|---|---|
| 3 | explore_functional_unit | Le module AP gère les factures fournisseurs. |
| 11 | element_exists/VendSettlement | REQ-001 Fit |
| 15 | get_sql_model/VendTable | La table VendTable contient… |
| 17 | find_relations/VendTable | VendTable, VendTrans |
| 19 | get_sql_model/VendTable | Colonnes: AccountNum… |
| 21 | get_security_links/AP | Rôle AP Clerk |
| 23 | get_entity_exposure/VendorV2 | Entité VendorV2 |
"""


def test_acceptance_parse_grounding_tags():
    """6 ✅ verified + 3 🔶 judgment tags in the acceptance FDD."""
    claims = parse_grounding_tags(_ACCEPTANCE_FDD)
    verified = [c for c in claims if c.kind == "verified"]
    judgments = [c for c in claims if c.kind == "judgment"]
    assert len(verified) == 6, f"Expected 6 verified, got {len(verified)}"
    assert len(judgments) == 3, f"Expected 3 judgments, got {len(judgments)}"


def test_acceptance_build_grounding_registry():
    """Registry contains exactly the 6 verified claims with correct sources."""
    claims = parse_grounding_tags(_ACCEPTANCE_FDD)
    registry = build_grounding_registry(claims)
    assert len(registry) == 6
    sources = {r["source"] for r in registry}
    assert "explore_functional_unit" in sources
    assert "element_exists/VendSettlement" in sources
    assert "get_sql_model/VendTable" in sources
    assert "find_relations/VendTable" in sources
    assert "get_security_links/AP" in sources
    assert "get_entity_exposure/VendorV2" in sources


def test_acceptance_find_unverified_claims():
    """3 explicit 🔶 judgment tags and 0 untagged table heuristic hits (all tables carry ✅)."""
    issues = find_unverified_claims(_ACCEPTANCE_FDD)
    judgment_issues = [i for i in issues if i["kind"] == "judgment"]
    assert len(judgment_issues) == 3
    # The VendTable bare-table sentences all carry ✅, so no heuristic hits for them.
    heuristic_hits = [i for i in issues if i["kind"] == "heuristic"]
    assert len(heuristic_hits) == 0, (
        f"Unexpected heuristic hits: {heuristic_hits}"
    )


def test_acceptance_validate_fdd():
    """Complete acceptance FDD passes validate_fdd with ok=True."""
    report = validate_fdd(_ACCEPTANCE_FDD)
    assert report["ok"] is True, f"validate_fdd failed: {report}"
    assert report["missing_sections"] == []
    assert report["has_grounding_appendix"] is True
    assert report["verified_count"] == 6
    assert report["judgment_count"] == 3
```

### Step 2: Run the acceptance tests

Run: `$env:PYTHONPATH='src'; pytest tests/test_spec_grounding.py -q -k acceptance`
Expected: all 4 acceptance tests pass.

If `test_acceptance_validate_fdd` fails due to a missing section match, check the `_DEFAULT_REQUIRED_SECTIONS` substrings in `spec_grounding.py` against the `_ACCEPTANCE_FDD` section headers — adjust the substring list (case-insensitive match, so "objets aot" matches "## Objets AOT impactés").

### Step 3: Run the full suite

Run: `$env:PYTHONPATH='src'; pytest -q`
Expected: all prior tests pass + new spec_grounding tests, 0 failures. Run: `ruff check src/d365fo_agent/spec_grounding.py`.

### Step 4: Commit

```bash
git add tests/test_spec_grounding.py
git commit -m "test: acceptance round-trip for spec_grounding (mini-FDD)"
```

---

## Task 5: Docs — reference the skill in README + `docs/mcp-server.md`

**Files:**
- Modify: `README.md`
- Modify: `docs/mcp-server.md`

### Step 1: Add the Functional-Spec Skill section to `README.md`

Insert after the existing "Functional documentation grounding" section (added in Phase 1) the following block:

```markdown
### Functional Design Documents (Feature 2)

The `skills/functional-spec/` skill lets an agent autonomously produce a
**grounded Functional Design Document** for any D365 F&O topic.

Every factual claim is verified against the AOT index or the documentation
index before it is written:

- ✅ `[VÉRIFIÉ: <tool>]` — verified via MCP tool or doc chunk
- 🔶 `[JUGEMENT — à confirmer]` — functional reasoning; flagged for review

**Usage:**

```
/functional-spec  <topic>
```

or, from Claude Code with the skill loaded:

```
functional-spec: produce an FDD for the Accounts Payable invoice matching process
```

**Orchestration order** (all tools are existing MCP tools):
`explore_functional_unit` → impacted objects → fit-gap / `search_docs` →
`get_security_links` → `get_sql_model` → `get_guidance` → FDD template →
optional `.docx` export.

**Anti-hallucination check** (Python, no extra deps):

```python
from d365fo_agent.spec_grounding import validate_fdd
report = validate_fdd(open("my-fdd.md").read())
print(report)  # {"ok": True/False, "missing_sections": [...], ...}
```

FDD template: `skills/functional-spec/templates/fdd-template.md`
```

### Step 2: Add the tool reference to `docs/mcp-server.md`

Append after the `docs_stats` tool entry (Phase 1) the following section:

```markdown
## Functional Design Document skill

The `skills/functional-spec/SKILL.md` is an agent-facing instruction file that
orchestrates the **existing** 27 MCP tools in a prescribed order to produce a
grounded FDD. No new MCP tools are added by Feature 2.

### Anti-hallucination helpers (`spec_grounding.py`)

```python
from d365fo_agent.spec_grounding import (
    parse_grounding_tags,      # find ✅/🔶 claims in a Markdown FDD
    build_grounding_registry,  # build the appendix registry from verified claims
    find_unverified_claims,    # surface 🔶 tags + heuristic bare-fact sentences
    validate_fdd,              # check all 13 required sections + appendix present
)
```

All functions are stdlib-only and take a Markdown string; no server connection
required. See `tests/test_spec_grounding.py` for usage examples.

### FDD template

`skills/functional-spec/templates/fdd-template.md` — the canonical 13-section
template with tag examples and grounding-appendix stub. Copy, fill, validate.
```

### Step 3: Run the full test suite one final time

Run: `$env:PYTHONPATH='src'; pytest -q`
Expected: all prior tests (~194) + spec_grounding tests pass, 0 failures.

### Step 4: Commit

```bash
git add README.md docs/mcp-server.md
git commit -m "docs: reference functional-spec skill and spec_grounding helpers"
```

---

## Self-Review

### 1. Coverage vs design §5–§7

| Design requirement | Covered by | Status |
|---|---|---|
| §5 skill orchestrating existing MCP tools | `SKILL.md` orchestration order (Task 3) | ✅ |
| §5 orchestration order (all 8 steps) | SKILL.md Steps 1–9 exactly match design §5 list | ✅ |
| §5 no new MCP tools | Plan explicitly states "no new MCP tools"; SKILL.md orchestrates existing 11 tools | ✅ |
| §6 FDD template sections (13) | `fdd-template.md` has all 13 sections; `_DEFAULT_REQUIRED_SECTIONS` list is the authoritative enum | ✅ |
| §7 inline ✅/🔶 tags | Tag syntax locked in plan §Tag-syntax; enforced in `parse_grounding_tags` regex | ✅ |
| §7 grounding appendix | `build_grounding_registry` + `validate_fdd` check + appendix section in template | ✅ |
| §7 unverified = judgment | `find_unverified_claims` surfaces 🔶 tags + heuristic bare facts | ✅ |
| export .docx | SKILL.md Step 9 delegates to `anthropic-skills:docx` skill (reference, not re-impl) | ✅ |
| Python helper testable + stdlib-only | `spec_grounding.py` — `re`, `dataclasses` only | ✅ |
| Tests grounded on synthetic examples | All tests use inline string fixtures; acceptance test uses a full mini-FDD | ✅ |

### 2. Placeholder scan

Every code block in this plan is **complete and runnable**. Search for TBD/TODO/FIXME/…:
- `fdd-template.md` uses `{{PLACEHOLDER}}` markers — these are **intentional** template slots for the agent to fill; they are not implementation placeholders.
- No Python source block contains `pass`, `TODO`, `raise NotImplementedError`, or `...` as a body.

### 3. Type consistency

| Symbol | Defined in | Used consistently in |
|---|---|---|
| `Claim.kind` | `spec_grounding.Claim` | `parse_grounding_tags`, tests (`"verified"` / `"judgment"`) |
| `Claim.source` | `spec_grounding.Claim` | `build_grounding_registry` (`c.source`), acceptance test sources set |
| `Claim.line` | `spec_grounding.Claim` | `build_grounding_registry` (`c.line`), `test_parse_claim_carries_line_number` |
| `validate_fdd` return keys | `spec_grounding.validate_fdd` | All `validate_fdd` tests check `ok`, `missing_sections`, `has_grounding_appendix`, `verified_count`, `judgment_count`, `unverified_issues` |
| `find_unverified_claims` return keys | `spec_grounding` | Tests check `kind`, `line`, `text` |
| `_DEFAULT_REQUIRED_SECTIONS` substrings | `spec_grounding` | Must be substrings of the actual `## Header` text in both `fdd-template.md` and `_ACCEPTANCE_FDD` — verified in Task 4 Step 2 note |

### 4. Skill location rationale

No `skills/` or `.claude/skills/` directory existed in the repository at plan-writing time. The plan creates `skills/functional-spec/` as a new first-class directory at the repo root. This follows the same co-location pattern as `data/guidance/` (bundled knowledge topics) and keeps the skill alongside the code it depends on. If a different skills convention is adopted project-wide, move the directory; the SKILL.md content is path-independent.
