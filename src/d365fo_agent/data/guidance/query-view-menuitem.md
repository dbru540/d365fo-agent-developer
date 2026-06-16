---
id: query-view-menuitem
title: Queries, views and menu items
summary: Build an AOT query (ranges/joins), a view (a reusable read model), and wire UI via menu items.
platform: d365fo
object_types: AxQuery, AxView, AxMenuItemDisplay, AxMenuItemAction
grounds: CustAccountStatementExt, CustAccountName, CustBillOfExchangeCancel
example_type: AxQuery
example_query: Cust
related_topics: form-patterns, data-entity-odata
related_tools: scaffold_object, get_signature, find_similar_examples, validate_xml
---
## Syntax
- **AxQuery**: a root datasource + child datasources joined (`InnerJoin`/`OuterJoin`/`ExistsJoin`),
  with `QueryBuildRange` filters. Used by forms, reports, data entities and batch.
- **AxView**: a saved read-only projection over a query/datasources exposing selected fields —
  the reusable building block behind many entities (see [[data-entity-odata]]).
- **AxMenuItem** (Display/Output/Action): the launch point that binds a form (Display), a report
  (Output) or a class/job (Action) into menus and security.

## Rules
- Secure every menu item — a menu item is the entry point a privilege grants
  ([[security-wiring]]); an unsecured one is a hole.
- A Display menu item points to a form, Output to a report, Action to a runnable class
  (RunBase/SysOperation) — match the kind to the target.
- Views and queries reference real tables/fields; verify them rather than guessing.

## Logic
Prefer a view when several consumers need the same shaped read; prefer a query when a single form
or report drives the filtering. Scaffold from a real query/view of a similar shape, then adjust
datasources, joins and ranges.

## Pitfalls
- Unsecured menu item → access-control gap.
- Wrong join type (Inner vs Exists) changing row multiplicity unexpectedly.
- Re-implementing in a view what an existing standard view already exposes.
