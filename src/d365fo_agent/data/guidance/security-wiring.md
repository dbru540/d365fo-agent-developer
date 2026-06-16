---
id: security-wiring
title: Wire security (privilege → duty → role)
summary: Grant access correctly — a privilege grants nothing until it is reachable from a role through a duty.
platform: d365fo
object_types: AxSecurityPrivilege, AxSecurityDuty, AxSecurityRole
grounds: CustTable, VendTable
example_type: AxSecurityPrivilege
example_query: privilege
related_topics: data-entity-odata, coc-extension
related_tools: wire_security, get_security_links, lint_artifact
---
## Syntax
A privilege grants effective access on entry points (menu items, data entities, services) with an
explicit access level (`Read`/`Update`/`Create`/`Delete`/`Correct`). Duties group privileges;
roles group duties. Extend standard duties/roles with `AxSecurityDutyExtension` /
`AxSecurityRoleExtension` named `<StdObject>.<suffix>`.

## Rules
- A privilege grants NOTHING until it is reachable from a role THROUGH a duty. Always emit the
  full `privilege → duty → role` chain; `wire_security` does this (extension-first by default).
- The granted access level must match the operation: a write needs `Update`/`Create`, never
  `Read` (the `privilege-grant-explicit` linter rule flags an implicit/insufficient grant).
- Extension naming `<StdObject>.<suffix>` puts the model prefix on the suffix (the linter checks
  the segment after the dot).

## Logic
Decide extension-first: extend an existing standard duty/role rather than inventing a new one,
unless the access genuinely is a new business function. Reference the target by name — wiring
does not need the target's XML content, so an unverified standard target WARNS (does not block),
unlike `derive_entity` which must read the source.

## Pitfalls
- A privilege with no duty/role path → looks configured, grants nothing.
- `Read` level on a write entry point → silent insufficient access at runtime.
- Same-named privilege mistaken for a duty (a name-only check passes, the typed check does not).
