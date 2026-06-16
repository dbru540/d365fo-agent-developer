---
id: ax2012-security
title: Role-based security in AX 2012 (privilege → duty → role)
summary: AX 2012 role-based security — privileges grant entry points, grouped by duties, granted to roles.
platform: ax2012
object_types: AxSecurityRole
example_type: AxSecurityRole
example_query: role
related_topics: ax2012-customization-model
related_tools: get_signature, search_corpus, find_similar_examples
---
## Syntax
Security objects live under the AOT `Security` node: `Roles`, `Duties`, `Privileges`. A role lists
duties; a duty lists privileges; a privilege grants access levels (Read/Update/Create/Delete/
Correct) on entry points (menu items, tables, service operations).

## Rules
- The chain is the same shape as D365 (`privilege → duty → role`) but it is defined in the AOT
  Security node, not as separate extension objects — there is no extension model, you add/edit the
  role/duty/privilege directly in your layer.
- A privilege grants nothing until a role reaches it through a duty.
- The access level must match the operation (a write needs Update/Create, not Read).
- Process cycles group duties for segregation-of-duties analysis.

## Logic
Reuse standard duties/privileges where possible; create custom privileges for custom entry points
and attach them to the appropriate (often standard) duty, then ensure a role carries that duty.

## Pitfalls
- A custom privilege with no duty/role path → no effective access.
- Read-level grant on a write entry point → silent insufficient access.
- Editing standard roles in place instead of adding a custom role/duty → upgrade conflicts.
