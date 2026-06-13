# D365 F&O Knowledge MCP Server

A vendor-neutral [MCP](https://modelcontextprotocol.io) server that grounds any coding agent
(Claude Code, Codex, Gemini CLI, …) in **real D365 AOT facts** so it can generate high-quality
X++ instead of guessing. It exposes deterministic tools over stdio: verify an element exists,
read its real signature, walk extension/security/entity relationships, retrieve idiomatic
in-corpus examples, generate artifacts from a spec, and validate the resulting XML.

It is **standard-library only** — no `mcp` pip package, no Node, no server process to host. It
runs anywhere Python ≥ 3.11 runs.

## Why this makes the LLM autonomous

The #1 X++ generation failure is a hallucinated name (a class/table/method that does not exist)
or wrong wiring (missing extension hop, `Read`-only privilege on a write operation). This server
gives the agent the tools to **check facts at generation time**:

| Need | Tool |
|---|---|
| Does this class/table/EDT exist? | `element_exists` |
| What are its real methods / fields / operations? | `get_signature` |
| What does it extend, what extends it? | `get_extension_chain` |
| How is it secured? | `get_security_links` |
| How is the entity exposed (OData/DM)? | `get_entity_exposure` |
| Show me idiomatic examples for this task | `find_similar_examples` |
| Give me a starting skeleton for a NEW object of ANY type | `scaffold_object` |
| Find by text / by exact name | `search_corpus`, `find_element` |
| What references this symbol? | `find_reverse_references`, `find_references` |
| Plan / generate artifacts from a spec | `analyze_spec`, `generate_from_spec` (~20 deterministic families incl. **class**, **table**, enum, edt, view, their `*-extension`s, data-entity, query, service, menu-item, security) — multi-artifact specs generate a wired SET (the agent fills method bodies) |
| Expose a standard entity via OData (duplicate it) | `derive_entity` |
| Grant a privilege through a duty/role (extension-first) | `wire_security` |
| Is my generated XML well-formed/structured? | `validate_xml` |
| Does it follow the X++ coding rules? | `lint_artifact` (index-backed) |
| Does it actually COMPILE? (real xppc.exe) | `compile_model` (Windows host) |
| What are the rules? | `get_methodology` |
| What does the corpus cover? | `index_stats` |

**Every AOT object type is covered.** The index walks *all* `Ax*` element folders (not a curated
whitelist), so it grounds the agent on the full AOT — ~70+ object types, ~233k elements — including
the `*Extension` families (AxDataEntityViewExtension, AxEnumExtension, AxEdtExtension, …), workflows
(AxWorkflowApproval/Template/Task), aggregations (AxAggregateMeasurement, AxCompositeDataEntityView),
AxView/AxQuery/AxMap, AxTile/AxKPI/AxPage, AxSecurityPolicy, AxConfigurationKey, and more. To help
code a NEW object of *any* of these, call `scaffold_object` (clones a real example of that type as a
starting skeleton) — there is no per-type template to maintain. `index_stats.supported_object_types`
lists the full set.

## Prerequisite — build the index once

The server reads a SQLite FTS5 index. Build it (custom corpus + the standard
`PackagesLocalDirectory` so the agent knows the standard D365 classes/APIs):

```powershell
$env:PYTHONPATH='src'
python -m d365fo_agent.cli build-index `
  --repo-root .\D365_repo\Contoso `
  --rules .\config\contoso.rules.json `
  --db .\.omx\index\d365fo.db `
  --packages-root .\D365_repo\Contoso\PackagesLocalDirectory `
  --rebuild
```

This indexes ~167k artifacts (custom + standard) in seconds. Re-run with `--rebuild` after the
corpus changes; omit `--packages-root` to index only the custom code.

`--repo-root` is repeatable: pass it once per custom corpus and they are merged into one
index in a single pass (rebuilding the custom side replaces ALL custom rows, so always list
every corpus together). Source layouts `src/xplusplus/models` and `xplusplus/models` are both
detected. When serving, pass each additional corpus to `serve-mcp` with `--extra-root <path>`
so the source-reading tools (signatures, examples, scaffold) can resolve its XML files.

### Optional: SQL data model (`get_sql_model`)

If you extract the SQL metadata of a deployed D365 database (views = the SQL counterparts of
data entities, base tables, typed columns, primary keys, functional-unit classification) into a
SQLite file, pass it with `serve-mcp --sql-model <sqlmodel.db>` (env `D365FO_SQL_MODEL`; a
`sqlmodel-raw.db` sitting next to the knowledge index is picked up automatically). This enables
the `get_sql_model` tool: the REAL SQL shape of an entity or table — typed columns, the base
tables it reads (each tagged with its functional unit: invoice, settlement, financial
dimensions, ...), and optionally the full T-SQL view definition. Grounds OData / Data
management / BYOD / reporting work in the physical model.

AX tables define no SQL foreign keys — the relational graph lives in the AOT `<Relations>`
metadata. Extract it into the same model with:

```powershell
python -m d365fo_agent.cli extract-aot-relations `
  --db .\.omx\index\sqlmodel-raw.db `
  --root .\D365_repo\Contoso\PackagesLocalDirectory `
  --root .\D365_repo\Contoso\src
```

`find_relations` then returns the AOT relations between two tables (relationship type,
cardinalities, exact join fields), and table lookups gain `aot_relations` /
`aot_referenced_by_count` — foreign-key-grade answers without any foreign keys.

## Wiring it into a coding agent

### Claude Code (`.mcp.json` in the project root)

```json
{
  "mcpServers": {
    "d365fo": {
      "command": "python",
      "args": [
        "-m", "d365fo_agent.cli", "serve-mcp",
        "--repo-root", "D365_repo/Contoso",
        "--rules", "config/contoso.rules.json",
        "--db", ".omx/index/d365fo.db",
        "--packages-root", "D365_repo/Contoso/PackagesLocalDirectory"
      ],
      "env": { "PYTHONPATH": "src" }
    }
  }
}
```

Restart Claude Code; the `d365fo` tools appear. Ask it to read `get_methodology` first. This
Windows-native config (also shipped as `.mcp.json` in the project root) is the recommended one —
the server itself is **not** affected by the Windows MAX_PATH limit (its DB lives at a short path
and it reads files well under 260 chars). MAX_PATH only ever tripped the *test suite's* deep
generated paths, which is why the two failing tests pass under WSL but the server runs fine on
Windows.

### WSL variants

WSL (Linux, `PATH_MAX` = 4096) sidesteps MAX_PATH entirely — useful for running the test suite
and for an all-Linux dev setup. The same SQLite index file works from either OS (it stores
relative paths), so no rebuild is needed when switching.

**(A) Claude Code running *inside* WSL** — paths are the project root under `/mnt/c`:

```json
{
  "mcpServers": {
    "d365fo": {
      "command": "python3",
      "args": [
        "-m", "d365fo_agent.cli", "serve-mcp",
        "--repo-root", "D365_repo/Contoso",
        "--rules", "config/contoso.rules.json",
        "--db", ".omx/index/d365fo.db",
        "--packages-root", "D365_repo/Contoso/PackagesLocalDirectory"
      ],
      "env": { "PYTHONPATH": "src" }
    }
  }
}
```

**(B) Claude Code on Windows, server running in WSL** — launch through `wsl.exe` (non-login
`bash -c` so no shell banner pollutes the stdio JSON stream):

```json
{
  "mcpServers": {
    "d365fo": {
      "command": "wsl.exe",
      "args": [
        "-e", "bash", "-c",
        "cd '/path/to/d365fo-agent' && PYTHONPATH=src python3 -m d365fo_agent.cli serve-mcp --repo-root D365_repo/Contoso --rules config/contoso.rules.json --db .omx/index/d365fo.db --packages-root D365_repo/Contoso/PackagesLocalDirectory"
      ]
    }
  }
}
```

Note: `/mnt/c` access from WSL is slower than native Linux FS (a full `build-index --rebuild`
takes ~1–3 min vs ~9 s on Windows). The actual D365 compile / Best-Practice loop still requires a
Windows host regardless.

### Codex / Gemini CLI / other MCP hosts

Any host that speaks MCP stdio uses the same command. The generic shape:

- **command:** `python`
- **args:** `-m d365fo_agent.cli serve-mcp --repo-root <repo> --rules <rules.json> --db <db> [--packages-root <pkgs>]`
- **env:** `PYTHONPATH=src` (or install the package so `d365fo-mcp` is on PATH and use that)

The console entry point `d365fo-mcp` (declared in `pyproject.toml`) is equivalent to
`python -m d365fo_agent.mcp_server` and reads the same flags or the env vars
`D365FO_REPO_ROOT`, `D365FO_RULES`, `D365FO_DB`, `D365FO_PACKAGES_ROOT`, `D365FO_METHODOLOGY`.

## The verify-driven workflow the agent should follow

1. `get_methodology` — load the rules once.
2. `find_similar_examples` — ground the change in real custom-code patterns.
3. `element_exists` / `get_signature` — verify EVERY element before referencing it.
4. `get_extension_chain` / `get_security_links` / `get_entity_exposure` — wire it correctly.
5. `generate_from_spec` (or hand-write following the example) — its response already includes
   an auto-`lint` of each generated file.
6. `validate_xml` (structure) **and** `lint_artifact` (coding rules) — fix every `error` before
   presenting.
7. Present the change with its evidence (examples used, what was verified, impact).

## Worked example: expose a standard entity via OData

"Make the standard `CustCustomerV3Entity` available on the OData API" — you cannot edit the
standard entity, so you duplicate it. `derive_entity` does the whole pattern in one call:

1. `element_exists` / `search_corpus` to confirm the source entity name.
2. `derive_entity` with `source_entity`, a prefixed `new_name`, the public names, a label in YOUR
   model's label file, and the grants:

   ```json
   {
     "source_entity": "CustCustomerV3Entity",
     "new_name": "BABCustomerExportEntity",
     "public_entity_name": "BABCustomerExport",
     "label": "@BABAccountsPayable:CustomerExport",
     "data_management": true, "staging_table": "BABCustomerExportStaging",
     "grants": ["Read", "Create", "Update"], "integration_mode": "OData"
   }
   ```

   It **clones the real entity XML** (all ~289 mapped fields/datasources/keys preserved — not a
   stub), sets `IsPublic=Yes` + the public names, relabels, renames the backing class, and builds
   the matching **security privilege** (`DataEntityPermissions`). Both come back validated +
   linted, with a review checklist.
3. **`wire_security`** — a privilege alone grants nothing; it must be reachable from a role,
   normally through a duty. Extension-first by default (no overlayering): add the privilege to an
   existing standard duty and/or attach it to an existing standard role. Pass `suffix` = your model
   name so the extension names (`<StandardObject>.<suffix>`) carry your prefix.

   ```json
   {
     "privilege": "BABCustomerExportEntityMaintain",
     "duty": "VendVendorMasterMaintain",
     "role": "VendInvoiceAccountsPayableManager",
     "suffix": "BABCustomerExport"
   }
   ```

   It emits an `AxSecurityDutyExtension` and an `AxSecurityRoleExtension` (the role references the
   duty), each validated + linted, plus the `privilege -> duty -> role` chain. Set
   `extend_duty`/`extend_role` to `false` to instead **create** a new custom `AxSecurityDuty` /
   `AxSecurityRole`. Extension targets are checked against the index by type; an unverified target
   is surfaced in `warnings`/`target_checks` (it does **not** block — confirm the exact standard
   name or switch to create-mode).

CLI equivalents:
`python -m d365fo_agent.cli derive-entity --repo-root … --db … --source CustCustomerV3Entity
--new-name BABCustomerExportEntity --output-dir gen --data-management --grants Read,Create,Update`
then `python -m d365fo_agent.cli wire-security --privilege BABCustomerExportEntityMaintain
--duty VendVendorMasterMaintain --role VendInvoiceAccountsPayableManager --suffix BABCustomerExport
--output-dir gen --db .omx/index/d365fo.db`.

See [`x++-methodology.md`](x%2B%2B-methodology.md) for the full behavioural contract.

## Verification ladder

1. **`validate_xml`** — offline, always available (well-formedness + correct AOT structure) for ANY
   AOT type. Structural rules = hand-curated for the common families + a corpus-LEARNED profile
   (`aot-type-profiles.json`, built once by `build-type-profiles`) for the long tail; the report's
   `rule_source` is curated/learned/generic. Build it: `python -m d365fo_agent.cli build-type-profiles
   --repo-root <repo> --db <db> --packages-root <PLD>` (writes `<db dir>/aot-type-profiles.json`,
   which the server auto-loads). Without it, unknown roots fall back to a Name-only generic check.
2. **`lint_artifact`** — X++ coding rules, index-backed (offline).
3. **`compile_model`** — the REAL X++ compiler (`xppc.exe`), driven by `d365fo_agent.build.XppCompiler`.
   It compiles a single model against the package metadata and returns structured diagnostics
   (errors/warnings with element + location) parsed from the compile log; `appchecker=true` also runs
   the Best-Practice (Appchecker) rules. This is **Windows-only** — `xppc.exe` is a .NET Framework
   assembly that ships in `PackagesLocalDirectory/bin`. It runs **directly on a Windows host, no
   Docker** (a Linux Docker engine cannot run it; that is not the path). When `xppc.exe` is absent it
   returns `status="unavailable"` so the agent knows the rung could not run here.

CLI: `python -m d365fo_agent.cli compile-model --packages-root <PLD> --model <Model> --output-dir gen [--appchecker] [--xref]`.
4. **`compile_generated`** — closes the generate->compile loop: temporarily overlays freshly-GENERATED
   artifacts into their model in the PLD, compiles, then ALWAYS restores the PLD. Use it right after
   `generate_from_spec` to prove the new X++ actually compiles (the compiler diagnostics flow back so
   the agent can fill/fix the method bodies and re-check). CLI:
   `compile-generated --packages-root <PLD> --model <Model> --generated-dir <gen> --output-dir <out>`.

## Quick manual smoke test

```powershell
$env:PYTHONPATH='src'
'{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{}}}' |
  python -m d365fo_agent.cli serve-mcp --repo-root .\D365_repo\Contoso --rules .\config\contoso.rules.json --db .\.omx\index\d365fo.db
```

A JSON-RPC `initialize` result on stdout means the server is live.
