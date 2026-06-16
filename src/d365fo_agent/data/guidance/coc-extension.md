---
id: coc-extension
title: Chain of Command (method wrapping)
summary: Extend a standard method without overlayering, using a final extension class with [ExtensionOf].
platform: d365fo
object_types: AxClass
grounds: CustTable, VendTable
example_type: AxClass
example_query: ExtensionOf
related_topics: table-extension-fields, event-handler
related_tools: get_signature, find_similar_examples, scaffold_object, compile_generated
---
## Syntax
Declare a `final` class decorated with the target's `[ExtensionOf(...)]` attribute and re-declare
the method with the SAME signature, calling `next` to run the original:

```
[ExtensionOf(tableStr(CustTable))]
final class CustTable_Bab_Extension
{
    public void insert()
    {
        next insert();          // run the standard logic
        // custom logic here
    }
}
```

Attribute forms: `tableStr(Name)`, `classStr(Name)`, `formStr(Name)`, `formDataSourceStr(Form, DS)`.

## Rules
- The class MUST be `final`.
- The class name MUST carry the model prefix and end with `_Extension` (convention; the linter's
  `naming-prefix` rule checks the segment after the dot).
- For a non-void wrapped method you MUST call `next` and return its value (or a typed value).
- You may only wrap methods that are accessible (public/protected); you cannot wrap private kernel
  methods. CoC wraps; it does not replace.
- One extension class can wrap several methods of the same target.

## Logic
Prefer Chain of Command when you must change the behaviour of an EXISTING method end-to-end.
Prefer an event handler (pre/post or a delegate) when the platform already exposes an extension
point for the exact moment you need — it is looser-coupled and survives signature changes. CoC is
compile-time bound to the signature, so a standard signature change breaks your wrapper.

## Pitfalls
- Forgetting `next` silently drops the standard behaviour.
- Wrapping a method that has no stable signature (frequently changed by Microsoft) is fragile.
- CoC on data methods (insert/update/delete) runs per row — keep it cheap.
