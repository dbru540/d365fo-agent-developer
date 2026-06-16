---
id: form-patterns
title: Forms and form extensions
summary: Form structure (datasources, design, controls) and how to extend a standard form without overlayering.
platform: d365fo
object_types: AxForm, AxFormExtension
grounds: CustTable, SalesTable
example_type: AxForm
example_query: CustTable form
related_topics: table-extension-fields, event-handler
related_tools: scaffold_object, get_signature, find_similar_examples, validate_xml
---
## Syntax
A form has: a `<SourceCode>` classDeclaration (the form's `FormRun`-derived behaviour), one or more
`AxFormDataSource` (each bound to a Root Table / Root Data Source), and a `<Design>` tree of
controls. A new field surfaces by adding a control bound to its datasource field.

A form EXTENSION (`AxFormExtension`, named `<Form>.<Model>`) adds controls/datasources or registers
event handlers WITHOUT modifying the standard form.

## Rules
- Add behaviour to a standard form via a form extension + event handlers (form/datasource/control
  events) — do NOT overlayer the standard form.
- Override form/datasource methods through Chain of Command on the datasource
  (`[ExtensionOf(formDataSourceStr(Form, DS))]`) or via form event handlers.
- A control must be bound to a datasource field that exists; adding a field to the table (see
  [[table-extension-fields]]) comes first.

## Logic
For a NEW form, scaffold from a real one of the right pattern (SimpleList, ListPage, Details)
rather than building blind — `scaffold_object(AxForm)` clones a real example. For changing a
standard form, extension + events is the upgrade-safe path.

## Pitfalls
- Overlayering a standard form instead of extending it → upgrade conflicts.
- Binding a control to a field that is not on the datasource → compile/runtime error.
- Forgetting the datasource's Root Table / Root Data Source on a new form (it will not compile).
