---
id: edt-enum-label-numseq
title: EDTs, enums, labels and number sequences
summary: The transverse fundamentals — typed data with EDTs/enums, labels instead of literals, and number sequences for IDs.
platform: d365fo
object_types: AxEdt, AxEnum
grounds: AmountCur, CustAccount, NoYes, NumberSequenceTable, NumberSequenceReference
example_type: AxEdt
example_query: Amount
related_topics: table-extension-fields, data-entity-odata
related_tools: get_signature, find_similar_examples, validate_xml, lint_artifact
---
## Syntax
- **EDT** (`AxEdt`): a reusable typed field definition (String/Real/Int/Date/Reference). A field's
  concrete table-field type derives from the EDT base (AmountCur → Real, CustAccount → String).
- **Enum** (`AxEnum`): a fixed value set; base/kernel enums (NoYes, ...) have no AOT XML but are
  valid. Reference an enum field with `<EnumType>`, an EDT field with `<ExtendedDataType>`.
- **Labels**: `@LabelFile:LabelId` — never a hard-coded string in UI/properties.
- **Number sequences**: `NumberSequenceReference` ties a scope to a `NumberSequenceTable` to
  generate record IDs; allocate via `NumberSeq::newGetNum(...)`.

## Rules
- Type fields through an EDT; do not invent a raw type (the `field-type-matches-edt` linter rule
  checks the field matches the EDT base — see [[table-extension-fields]]).
- Use a label, not a literal, for any user-visible text (the `label-not-literal` linter rule).
- Extend a standard EDT/enum with `AxEdtExtension`/`AxEnumExtension` rather than overlayering.
- Custom EDTs/enums/labels carry the model prefix.

## Logic
EDTs and enums are how X++ stays strongly-typed end to end (table field → form control → entity
column). Define the EDT once, reuse everywhere; add enum values by extension so upgrades are clean.

## Pitfalls
- `<ExtendedDataType>` on an enum field (should be `<EnumType>`) or vice versa.
- Hard-coded UI strings → fail Best Practice and break translation.
- Allocating IDs by hand instead of a number sequence → collisions/gaps.
