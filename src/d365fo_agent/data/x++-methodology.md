# X++ / D365 F&O Engineering Methodology

This is the behavioural contract for any LLM generating D365 Finance & Operations code through
this toolkit. It is served to agents by the MCP `get_methodology` tool. Treat it as binding
guidance, not background reading: when a rule here conflicts with a habit from generic coding,
the rule here wins.

The single most important principle: **verify, do not guess.** Before you reference any AOT
element (class, table, method, EDT, enum, data entity, security object), confirm it exists with
the `element_exists` / `get_signature` tools. A plausible-but-nonexistent name is the most
common and most damaging X++ generation error.

---

## 1. Extension-first, always

D365 F&O is an over-layered, upgrade-safe platform. You **never edit standard (Microsoft) or
ISV objects in place.** You extend them.

- Add fields to a table → **table extension** (`AxTableExtension`, named `<Table>.<Model>`).
- Change behaviour of a class/table/form method → **Chain of Command (CoC)** in a class marked
  `[ExtensionOf(...)]`, or an **event handler**.
- Add controls to a form → **form extension** (`AxFormExtension`).
- Add access to a role/duty → **role/duty extension**, never edit the standard role.

If you find yourself wanting to modify a standard artifact's XML directly, stop — model it as an
extension instead.

## 2. Chain of Command vs event handlers

Both are extension mechanisms. Choose deliberately:

- **Chain of Command (CoC)** — wrap a method with `[ExtensionOf(classStr/tableStr/formStr(Target))]`
  and call `next methodName(...)`. Use when you must run code **before/after** a method *and*
  potentially influence its return value or arguments. Requires the target method to be
  `public`/`protected` and hookable. Always call `next` exactly once unless you deliberately
  short-circuit (and document why).
- **Event handlers** — subscribe to a delegate or pre/post event. Use for **loosely coupled**
  reactions where you do not need to alter the return value, or when the target exposes a
  delegate/event specifically for extension. Prefer events when Microsoft provides one for your
  scenario.

Rule of thumb: need to change the outcome → CoC; need to react to it → event handler.

## 3. Naming conventions

- **Prefix every custom artifact** with your model/publisher prefix (in this corpus: `BAB`,
  `Fiveforty`, `FLexmind`). No unprefixed custom names.
- Table/class extensions: `<TargetObject>.<ModelName>` for the `*Extension` AOT element name
  (e.g. `CustTable.BABAccountsPayable`), and `<Target>_<Purpose>` for CoC classes
  (e.g. `CustTable_BABExtension`).
- Fields, methods, EDTs, enums: PascalCase, prefixed. EDTs end with their semantic role
  (e.g. `BABBfcAccountId`).

## 4. Labels, never hard-coded strings

- All user-facing text uses a **label reference**: `@<LabelFile>:<LabelId>`
  (e.g. `@BABExportBFC:BFCLedgerAccount`). Never embed a literal English string in a property
  that supports a label.
- Reuse an existing label if one fits (search the corpus). Create a new label in the model's own
  label file when needed.

## 5. Field types — get the AOT type right

When adding table fields, the AOT field element type must match the EDT/enum, or the field is
silently wrong:

- EDT based on `int64` / a `RefRecId` → `AxTableFieldInt64`.
- An enum (`NoYes`, custom enums) → `AxTableFieldEnum` with the enum type.
- Real / date / int / string → the matching `AxTableField{Real,Date,Int,String}`.

Do not default everything to `AxTableFieldString`. Use `get_signature` on a comparable existing
field to copy the right shape. When `generate_from_spec` runs with an index (`--db`), it resolves
each field's type from the EDT's real base type (reading the EDT's `i:type`) and emits the right
`AxTableField*` automatically — so you only fall back to `AxTableFieldString` when the EDT is
genuinely a string or absent from the corpus.

## 6. Security wiring

- A new menu item / form / service operation that users invoke must be secured by a **privilege**
  (`AxSecurityPrivilege`) with the correct entry-point grant (`Read`/`Update`/`Create`/`Delete`/
  `Correct` as appropriate — not `Read`-only by reflex).
- Privileges roll up into **duties**, duties into **roles**. Extend standard roles/duties via
  `*Extension` objects; do not edit them.
- **A privilege on its own grants nothing** — it must be reachable from a role, normally through a
  duty. After creating a privilege (e.g. from `derive_entity`), run **`wire_security`** to emit the
  duty/role wiring: extension-first by default (`AxSecurityDutyExtension` / `AxSecurityRoleExtension`
  on existing standard objects), or `extend_*=false` to create a new custom duty/role. Extending a
  standard **duty** propagates the privilege to every role that already carries it — often you do
  not also need a role extension.
- Use `get_security_links` to see how comparable objects are already secured before inventing a
  new privilege.

## 7. Data entities & OData

- A public data entity sets `IsPublic = Yes`, a `PublicEntityName`, and a `PublicCollectionName`
  (plural). For data management, `DataManagementEnabled = Yes` and a staging table.
- A real entity carries `Fields`, `Keys`, `Relations`, a `PrimaryKey`, and usually a `FormRef`.
  An entity with empty `Fields`/`Keys` is a stub, not a deliverable.
- Use `get_entity_exposure` to check how an existing comparable entity is exposed.

## 8. Workflow for every change request

1. **Identify the artifact family** — this works for ANY AOT object type, not a fixed shortlist.
   The index covers every `Ax*` type (~70+: classes, tables, views, queries, forms, entities and
   their `*Extension`s, workflows, aggregations, tiles, KPIs, security policies, config keys, …).
   For a NEW object of any type, call `scaffold_object(artifact_type=…, new_name=…)` to clone a real
   example of that type as a starting skeleton; `index_stats.supported_object_types` lists them all.
2. **Retrieve real examples** from the corpus with `find_similar_examples` — prefer
   `custom-canonical` examples over standard ones as the pattern source.
3. **Verify every referenced element** with `element_exists` / `get_signature`. Never reference
   an unverified name.
4. **Inspect relationships** (`get_extension_chain`, `get_security_links`, `get_entity_exposure`)
   so the change wires into the right places.
5. **Generate** the artifact(s) — via `generate_from_spec` when a structured spec exists, or by
   hand following the retrieved example's shape.
6. **Validate** the XML with `validate_xml` before presenting it. Fix every error; explain any
   remaining warning.
7. Present the change **with its evidence**: which examples grounded it, what you verified,
   what security/entity/upgrade impact it has.

## 9. Anti-patterns (do not do these)

- Referencing a class/table/method you did not verify exists.
- Editing standard or ISV objects in place instead of extending them.
- Hard-coded user-facing strings instead of labels.
- `AxTableFieldString` for non-string EDTs/enums.
- `Read`-only privilege grants when the operation creates/updates/deletes data.
- Data entities or form extensions emitted as empty stubs.
- Copying legacy / `legacy-deprecated`-classified patterns as if they were current best practice.
- Calling `next` zero or multiple times in a CoC method without a documented reason.

## 10. Verification ladder

1. `validate_xml` — well-formedness + structural sanity for ANY AOT type (offline, always available
   here). Structural rules come from hand-curated rules for the common families and a corpus-LEARNED
   profile (`aot-type-profiles.json`, built by `build-type-profiles`) for the long tail; the report's
   `rule_source` says which applied (curated/learned/generic).
2. `lint_artifact` — the coding rules in this document, **machine-enforced** (naming prefix,
   labels-not-literals, field-type-matches-EDT, extension-target-exists, no-legacy-reference,
   privilege grants, data-entity completeness). Index-backed, offline. Fix every `error`. Rule
   policy lives in `config/x++-rules.json`; logic in `src/d365fo_agent/linter.py`.
3. `compile_model` — the REAL X++ compiler (`xppc.exe`), structured diagnostics. Runs on a Windows
   host with `PackagesLocalDirectory/bin/xppc.exe` (NOT in a Linux Docker container — the compiler
   is a Windows .NET assembly). `appchecker=true` also runs the Best-Practice (Appchecker) rules.
   Returns `status="unavailable"` when the compiler is not on this host.
4. Cross-reference validation, deployable packaging — downstream of compile.

Steps 1–2 are offline and always available here; step 3 needs a Windows host (available on the dev
box). They are the floor, not the ceiling — state clearly which rungs you were able to run. Note:
the rules in this document are no longer prose only — steps 1–2 enforce the machine-checkable ones
automatically, and step 3 proves it actually compiles.
