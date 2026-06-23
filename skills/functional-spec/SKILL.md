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
