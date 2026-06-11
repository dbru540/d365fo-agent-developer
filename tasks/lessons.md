# Lessons

## 2026-06-09 — Building the operational MCP layer

- **`graphify` is a Claude *skill*, not a pip package.** `from graphify import build, cluster, …`
  is only satisfiable in an env where the skill's python is on the path. `pip install graphify`
  would pull an unrelated homonym and break the import. Keep it an **optional** dependency:
  import it lazily inside the one function that needs it (`run_graphify_staging`), declare it as a
  `[graph]` extra, and skip graphify-dependent tests when `importlib.util.find_spec('graphify')`
  is None. The CLI/MCP/index must never hard-depend on it.

- **Tests are `unittest`, not pytest-specific** — `python -m unittest discover -s tests` runs the
  whole suite with no pytest install. Run via `discover` (or `cd tests`) so sibling imports like
  `from test_catalog import …` resolve; `python -m unittest test_x` from the repo root fails to
  find them.

- **Windows MAX_PATH (260) is real here.** The working dir
  `C:\Users\DavidBru\FIVEFORTY\Documents\_WORK\540\_AI\x++` is already ~52 chars; the deepest
  generated AOT paths (`…\AxSecurityDutyExtension\AssetAccountingMaintain.BABAccountsPayable.xml`)
  push past 260 and `open()` fails with `FileNotFoundError` even after a successful `mkdir`. Two
  tests fail for this reason; it is environmental, not a code bug. Fix = enable
  `HKLM\…\FileSystem\LongPathsEnabled=1` (needs admin) or use a shorter base path / WSL. New code
  should keep its own paths short (index DB at `.omx/index/`).
  **RESOLVED 2026-06-09:** the two failing tests wrote under `<repo>/.test_tmp` (repo path ~65
  chars) + a ~199-char generated AOT suffix = >260. Pointing `TEST_TEMP_ROOT` (in
  `tests/test_catalog.py`) at the short system temp dir (`tempfile.gettempdir()/"d365fo_tests"`,
  overridable via `D365FO_TEST_TMP`) keeps every generated path under 260 — suite is now green on
  Windows Python AND WSL (102 tests, 0 errors). The error only ever showed because the suite was
  run with the *Windows* interpreter (MAX_PATH=260); WSL (PATH_MAX=4096) never tripped it.

- **Path-walk beats XML-parse for a standard-corpus symbol index.** Element name = file stem,
  type = parent folder, so walking `PackagesLocalDirectory/<pkg>/<model>/<AxType>/*.xml` indexes
  ~167k standard elements in seconds without parsing. **Watch the layout:** a package can hold
  many models and the model dir name is often *not* the package name (ApplicationSuite → Foundation,
  …) — enumerate model dirs explicitly or you silently miss the biggest packages.

- **SQLite FTS5 is the right local index.** It ships with CPython on Windows (`fts5` available),
  external-content tables mirror a normal `artifacts` table for free, and
  `INSERT INTO fts(fts) VALUES('rebuild')` builds the index in one shot. Quote each query token as
  `"tok"*` to neutralise FTS5 operators in user input.

- **A pure-stdlib MCP stdio server is enough.** MCP over stdio is newline-delimited JSON-RPC 2.0;
  implementing `initialize` / `tools/list` / `tools/call` / `resources/*` by hand avoids the `mcp`
  pip dep and keeps the "runs anywhere" property. Diagnostics MUST go to stderr (stdout is the
  protocol channel). Notifications (no `id`) get no response.

- **Tool descriptions must be prescriptive** ("call this BEFORE referencing any element") — recent
  models under-reach for tools by default, and the whole point of the server is to make the agent
  verify instead of guess.

- **Everything must be UTF-8 — and on Windows that is NOT the default.** `sys.stdout`/`stdin`
  default to **cp1252** on Windows, so writing any char outside that codepage (`✓` U+2713, CJK,
  many symbols — French accents happen to be IN cp1252, which masks the bug) raises
  `UnicodeEncodeError` and corrupts the JSON-RPC stream. MCP mandates UTF-8 on the wire. Fix applied
  at both entry points (`cli.main`, `mcp_server.serve_stdio`): reconfigure `stdin/stdout/stderr` to
  UTF-8 (`stream.reconfigure(encoding="utf-8")`, guarded so StringIO test doubles are skipped) and
  use `ensure_ascii=False` on every `json.dumps`/`json.dump` (wire, CLI output, and file-written
  manifests/bundles). All file I/O already passed `encoding="utf-8"` explicitly — never rely on the
  locale default (`read_text()` without encoding = cp1252 on Windows = silent corruption).
  Gotcha while testing: a verification harness that `print()`s the round-tripped unicode to the
  cp1252 *console* will itself crash — assert and print ASCII-only booleans, or check the raw bytes.

- **Formalise coding rules ESLint-style: logic in code, policy in data.** The X++ conventions in
  `docs/x++-methodology.md` (prose, LLM-facing) are now machine-enforced by `linter.py` —
  one check function per rule — with `config/x++-rules.json` controlling enable/severity/prefixes.
  Rule logic can't be pure data (conditions are code), but enable/severity/params should be. The
  high-value rules are **index-backed**: `field-type-matches-edt` resolves the EDT's base type from
  the index (so the EDT folder name must be granular — expand `AOT_TYPE_DIRECTORIES` to the full
  AxEdt* family), and `extension-target-exists` checks the target against the corpus. Index-backed
  rules must **degrade gracefully** (return `None` → reported in `rules_skipped`) when no index is
  supplied, never produce false findings. Wire the linter into `generate_from_spec` so the agent
  gets generation + rule check in one round-trip.

- **An EDT's real subtype is in its XML `i:type`, NOT in the index `artifact_type` — the standard
  corpus indexes EVERY EDT under a single generic `AxEdt` folder.** (Correction to the line above:
  `AOT_TYPE_DIRECTORIES` granularity only helps the *custom* corpus, where EDTs may sit in
  `AxEdtReal/…` folders; the standard PackagesLocalDirectory puts them all in one `AxEdt` folder
  with `<AxEdt i:type="AxEdtReal">`.) So resolving an EDT's base type for field typing requires
  READING the EDT file and reading the root's `i:type` attribute — `knowledge.resolve_edt_field_type
  (index, edt, roots)` does this (maps `AxEdtReal`→`AxTableFieldReal`, etc.). Consequence: the
  linter's `field-type-matches-edt` (which only used the folder-derived `artifact_type`) silently
  couldn't catch wrong types on STANDARD EDTs — **RESOLVED 2026-06-10: `_expected_field_type` takes
  `roots` and delegates to `resolve_edt_field_type`, so the linter reads `i:type` too** (`LintContext.
  roots`; MCP passes `file_roots`; CLI `lint --repo-root/--packages-root`; degrades to no-flag without
  roots). For GENERATION the gap is now closed:
  `generate_from_spec --db` threads a `FieldTypeResolver` callable (built from
  `resolve_edt_field_type`) through both the create and merge paths, so e.g. AmountCur→Real,
  TransDate→Date instead of the blanket AxTableFieldString. Pass the resolver as a callable, not the
  index, so the generator stays decoupled from the index/knowledge layer. **Verify the real layout
  before trusting `artifact_type`** — I assumed subtype folders existed and the first cut resolved
  nothing on real standard EDTs.

- **A generated artifact that only REFERENCES a target by name should WARN on an unverified
  target, not BLOCK.** `wire_security` (security_wiring.py) emits duty/role wiring for a privilege.
  It first hard-refused when the standard duty/role being extended wasn't in the index — wrong:
  unlike `derive_entity` (which needs the source entity's *XML content* to clone, so a missing
  source is fatal), wiring only references the target by *name*. Blocking on a partial index
  produces false negatives that stop legitimate work. Fixed to produce the artifact and surface the
  miss in `warnings`/`target_checks` (and lint flags it independently). Mirror `derive_entity`'s
  hard-fail only when you genuinely consume the target's content. **Two sharper points:** (1) the
  typed check `index.exists(name, 'AxSecurityDuty')` is more precise than the linter's
  `extension-target-exists`, which is name-only — a same-named *privilege* (`DataManagementOperations
  Maintain` exists as an AxSecurityPrivilege) would satisfy lint but is NOT a duty. (2) **The
  BabilouFinOps PackagesLocalDirectory mirror does not contain the base standard `AxSecurityDuty`/
  `AxSecurityRole` objects** — only standard *privileges* and the *custom* duties/roles/extensions.
  So extension-target verification of real standard duties/roles can never pass against this index;
  warn-don't-block is the only workable default. Extension naming is `<StdObject>.<suffix>` and the
  linter's naming-prefix rule checks the segment AFTER the dot — so the suffix must carry the model
  prefix (defaulted to the privilege name; pass your model name). All four security XML shapes
  (duty/role × extension/new) were grounded on real corpus files before coding — never guess.

- **To "copy a standard entity", CLONE its real XML — don't regenerate from a spec.** A real data
  entity is huge (CustCustomerV3Entity = 3744 lines, 289 mapped fields, datasources, methods);
  regenerating from a spec yields a useless stub (the old gap S03). The senior-dev pattern is
  duplicate-then-adjust: parse the source entity, upsert only the identity/exposure/label nodes
  (`Name`, `IsPublic`, `PublicEntityName`, `PublicCollectionName`, `Label`, `DataManagement*`) and
  rename the backing class in the `<Declaration>` (`\bclass <old>\b` → `class <new>`); everything
  else is preserved verbatim. `entity_derive.derive_public_entity` does this. The matching entity
  privilege uses `DataEntityPermissions`/`AxSecurityDataEntityPermission` (NOT EntryPoints) — shape
  grounded on a real corpus example (verify, don't guess). Honestly flag the bits a deterministic
  clone can't finish (method bodies that hard-code the old class name, cross-file label refs) in a
  review checklist rather than pretending they're done.

- **The X++ compiler runs directly on the Windows host — "Docker is available" was a red herring.**
  When the user offered Docker to close the compile rung, the reflex is "great, containerize the
  build." But `docker info` here reports the **Linux** engine, and `xppc.exe` is a **Windows .NET
  Framework** assembly (`file` → "PE32 … Mono/.Net assembly") — a Linux container cannot run it, and
  Wine on a 900 MB managed compiler is not a serious path. The real insight: we are ALREADY on a
  Windows host and `xppc.exe` ships in `PackagesLocalDirectory/bin` — it is a standalone compiler
  (`-metadata -modelmodule -output -referenceFolder -log [-RunAppcheckerRules] [-xref]`) that runs
  headless in ~5 s, NO AOS/Visual Studio/Docker needed. Verify the binary type and the docker OSType
  BEFORE designing a container pipeline. Also: don't assume a failing compile means an incomplete
  corpus — the first model hit a "Failed to write runtime metadata to disk" NRE + a missing-Commerce
  warning, which looked like a partial mirror, but the Commerce assembly WAS present and a *second*
  model compiled clean (exit 0). The fatal was model-specific, not environmental. Build the adapter
  to PARSE the compiler log (`Errors: N` / `Warnings: N` summary + `<Category> <Severity>: <msg>`
  lines with `dynamics://…` element + `[(line,col),…]` location) into structured diagnostics, and
  degrade to `status="unavailable"` (never crash) when `xppc.exe` is absent so the rung is portable.

- **Index EVERY `Ax*` folder, never a whitelist — a curated type list silently drops coverage.**
  (Supersedes the earlier "expand `AOT_TYPE_DIRECTORIES` to the full AxEdt* family" advice — the
  whole whitelist was the bug.) The standard-package scanner gated on a 25-entry
  `AOT_TYPE_DIRECTORIES` set, so ~50 AOT types / ~66k real objects were invisible to the agent
  (exists/signature/search/examples all returned nothing) — including the high-value `*Extension`
  families (AxDataEntityViewExtension, AxEnumExtension, AxEdtExtension), AxWorkflow*, AxAggregate*,
  AxTile, AxSecurityPolicy, AxConfigurationKey, AxCompositeDataEntityView, … Every real AOT element
  folder is named `Ax<Type>`, so the rule is simply: a dir whose name `startswith("Ax")` is a type
  folder (skip a tiny `_NON_AOT_DIRS` set: bin/Descriptor/Resources/XppMetadata/AdditionalFiles).
  **There were TWO such whitelists — fix BOTH:** `index_store.AOT_TYPE_DIRECTORIES` (the standard
  path-scan of PackagesLocalDirectory) AND `indexer.SUPPORTED_ARTIFACT_TYPES` (the rich CUSTOM parse
  of `src/xplusplus/models`, which was dropping the user's custom enums/EDTs/extensions from the
  *editable source*). The repo has BOTH `src` (editable X++ source — richest, the custom artifacts
  resolve here first) and `PackagesLocalDirectory` (deployed metadata + standard); a coverage fix
  that only touches the standard scanner still leaves custom `src` types invisible — grep every
  whitelist. Result: 25 → **72 types**, 166,988 → **233,688 artifacts** (custom 1152→**1372**,
  16→**36 types**), grounding now universal on both sources — and it needs no upkeep for new types.

- **To prove GENERATED X++ compiles, OVERLAY it into its model in the PLD, compile, then ALWAYS
  restore.** `generate_from_spec` writes source layout; `xppc` compiles a model from
  PackagesLocalDirectory — so a freshly-generated artifact can't be compiled until it sits in a
  compilable model. `XppCompiler.compile_overlay(model, overlays)` writes each artifact to
  `PLD/<package>/<model>/<AxType>/<name>.xml`, runs `compile_model`, and restores in a `finally`
  (added files unlinked, overwritten files written back from a bytes backup) — so an exception or
  timeout never leaves the PLD dirty. De-risk the idea with a throwaway probe before building the
  API (overlay one trivial class, compile, check Errors:0, delete) — it worked first try here.
  **GOTCHA: xppc writes a compiled-metadata BYPRODUCT** at
  `<package>/XppMetadata/<model>/<AxType>/<name>.xml` for each source artifact — restoring only the
  source you wrote LEAKS those into the user's PLD. Snapshot the XppMetadata counterpart too (None
  for a brand-new artifact) and restore/remove it in the same finally. A post-run `find` for your
  probe names (across the WHOLE PLD, not just the source folder) is how you catch the leak.
  **Generated method stubs must be COMPILABLE**, or the overlay-compile fails on the agent's behalf:
  emit `next <m>();` for CoC overrides and, for ANY non-void method, a typed-return placeholder
  `<RetType> _ret; return _ret;` (valid X++ for primitives, EDTs, tables, classes alike) — so the
  class compiles before the agent writes the logic. Also preserve method qualifiers (`static`/`final`)
  through the spec parser; the descriptor after `:` is `<qualifiers...> <return_type>`, not just
  `<visibility> <return_type>`. Validate-by-use (run a real spec→generate→compile ticket) is what
  surfaces these — the compiler is the honest judge of "how much did we actually fill in".

- **Packaging an MCP server for free distribution: ship the ENGINE, make the knowledge fetchable,
  and verify in a FRESH venv.** Goal: `pip install` an MCP server that already KNOWS X++ so users
  don't re-feed a repo each time. Key realisations: (1) the **standard D365 corpus is identical for
  everyone** (232k of 233k artifacts) — index it once and ship it as a downloadable asset; only the
  tiny custom slice is per-user (opt-in via `--repo-root`). (2) The index is **100 MB — too big for
  a wheel**; ship the engine in a ~90 KB wheel and download the index on demand (`fetch-knowledge`:
  stdlib `urllib`+`gzip` → `~/.d365fo-agent/d365fo.db`); `serve-mcp` defaults `--db` to that cache so
  it runs with NO repo. (3) **The #1 packaging bug: data files resolved relative to the source tree**
  (`Path(__file__).parents[2]/docs`) work in dev but VANISH after `pip install` (code lives in
  site-packages). Fix: bundle methodology/rules/default-profiles INTO the package (`data/`,
  `[tool.setuptools.package-data]`) and resolve via `importlib.resources.files("pkg").joinpath("data")`,
  with a source-tree fallback for dev. (4) **Only a fresh-venv install proves it** — `python -m build`
  → `venv` → install the wheel → run OUTSIDE the source tree; that is the only way the path-resolution
  bug surfaces. Also: `twine check dist/*` validates PyPI metadata + README render before upload; keep
  `requires-python`/`license`/`classifiers`/`project.urls` set; don't publish (twine upload / GitHub
  release) for the user — that needs their account. setuptools 65 predates PEP 639, so use
  `license = {text = "MIT"}` + the OSI classifier, not the SPDX `license = "MIT"` string.

- **To validate ANY object type, LEARN the structure from the corpus — don't hand-code 72 schemas.**
  `validate_xml` only knew ~18 roots (curated `ROOT_RULES`); for the rest it did a Name-only generic
  check, so a stripped `AxView` (just `<Name>`) wrongly passed. Fix (`type_profile.py`): sample ~200
  real examples per AOT type, record direct children that are near-universal (≥95% → `required`) vs
  common (≥40% → `recommended`), persist to `aot-type-profiles.json`. `validate_xml` resolves rules
  **curated → learned profile → generic** (`rule_source` reports which); curated stays authoritative
  for hand-verified families, the profile covers the long tail. Built offline like the index (the
  MCP server auto-loads the JSON next to the DB; degrades gracefully when absent — never a hard dep).
  The learned rules are genuinely correct (AxView→Fields/Relations/ViewMetadata, AxKPI→Goal/
  Measurement/Value, AxWorkflowApproval→Approve/Deny/Document) because the corpus IS the schema.
  General principle reused all session: when you need to cover "every X", derive the rule from the
  data (a naming convention, a frequency profile) instead of enumerating — it scales and self-updates.
  Corollary for "generate any object": don't write 72 deterministic templates — pair `scaffold_object`
  (clone a real example) with grounding + this universal validation; the verification chain is what
  makes generating an arbitrary type trustworthy, not a per-type generator. To "help code ANY object type", grounding-by-default beats per-type
  generators: pair universal indexing with `scaffold_object` (clone a real example of the requested
  type as a renamed skeleton) — corpus-driven, so one function covers all ~70 types instead of 70
  hand-written templates. When a request is "support every X", first check whether a whitelist/
  registry is quietly capping coverage; making the discovery rule structural (a naming convention)
  usually beats enumerating. Rebuild the index after the scanner change — coverage only changes on
  rebuild (`build-index --rebuild`); the running MCP server reads the file but does not lock it.
