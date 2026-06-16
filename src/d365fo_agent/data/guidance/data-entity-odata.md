---
id: data-entity-odata
title: Expose data via a data entity (OData / DMF)
summary: Create or duplicate a data entity, make it public for OData, and secure it — grounded on a real standard entity.
platform: d365fo
object_types: AxDataEntityView
grounds: CustCustomerV3Entity, CustTable
example_type: AxDataEntityView
example_query: CustomerV3 entity
related_topics: security-wiring, table-extension-fields
related_tools: derive_entity, get_entity_exposure, get_sql_model, validate_xml
---
## Syntax
A data entity (`AxDataEntityView`) maps a root datasource (a table) plus joined datasources to a
flat set of exposed fields. Key identity/exposure nodes:
`<IsPublic>Yes</IsPublic>`, `<PublicEntityName>`, `<PublicCollectionName>`, `<DataManagementEnabled>`.

## Rules
- To "copy" a standard entity, CLONE its real XML (datasources, mapped fields, keys) and adjust
  only the identity/exposure/label nodes + the backing staging class — do NOT regenerate a stub
  from a spec (you would lose hundreds of mapped fields). `derive_entity` does exactly this.
- A public entity needs a unique `PublicEntityName` and `PublicCollectionName`.
- The entity is reachable over OData only once it is public AND secured (see `security-wiring`).
- The SQL view that backs the entity is the physical truth: `get_sql_model` returns its real
  columns and base tables.

## Logic
Expose an entity when an external system needs read/write over OData or DMF needs an import/export
target. Duplicate-then-adjust is the senior pattern: start from the closest standard entity, make
it public, relabel, secure. Composite entities have no single SQL view by construction.

## Pitfalls
- Regenerating a huge entity from a spec → useless stub.
- Method bodies that hard-code the old backing class name after a clone.
- Forgetting to wire an entity permission → the OData endpoint returns 401/empty.
