---
id: table-extension-fields
title: Add fields to a standard table (table extension)
summary: Add fields, field groups and relations to a standard table via an AxTableExtension, with correct EDT/enum typing.
platform: d365fo
object_types: AxTableExtension
grounds: CustTable, AmountCur, TransDate, NoYes
example_type: AxTableExtension
example_query: CustTable extension
related_topics: coc-extension, data-entity-odata
related_tools: get_signature, validate_xml, lint_artifact, generate_from_spec
---
## Syntax
An extension is its own metadata object named `<Table>.<Model>` whose `<Name>` is e.g.
`CustTable.BabModel`. Each field carries the concrete `AxTableField*` type matching its source:

- EDT-backed field: `i:type="AxTableField<Base>"` + `<ExtendedDataType>AmountCur</ExtendedDataType>`
  where `<Base>` is the EDT's real base (Real/Int/String/Date/...).
- Base-enum field: `i:type="AxTableFieldEnum"` + `<EnumType>NoYes</EnumType>` (NOT
  `<ExtendedDataType>`).

## Rules
- The field's concrete type MUST match the EDT's base type. `AmountCur` → `AxTableFieldReal`,
  `TransDate` → `AxTableFieldDate`. A String field on a Real EDT is a defect the
  `field-type-matches-edt` linter rule catches (it reads the EDT's `i:type`).
- Custom field names carry the model prefix.
- Add the new field to a field group so it surfaces on forms; extensions can extend existing
  field groups.
- Relations and indexes can be added by the extension; you cannot remove standard ones.

## Logic
Reach for a table extension whenever you need to persist data on a standard table. Resolve the
field type from the EDT, never from a guess — the toolkit threads a field-type resolver through
`generate_from_spec --db` so generated fields get the real type up front.

## Pitfalls
- Emitting `<ExtendedDataType>` for a base enum (should be `<EnumType>`).
- Defaulting unknown fields to `AxTableFieldString` instead of resolving the EDT.
- Forgetting the field group, so the field never appears in the UI.
