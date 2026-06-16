---
id: ax2012-customization-model
title: Customize AX 2012 (layers & events — NOT Chain of Command)
summary: AX 2012 has no Chain of Command; you customize by overlayering in a higher layer/model or with event handlers.
platform: ax2012
object_types: AxClass
example_type: AxClass
example_query: class
related_topics: ax2012-security
related_tools: get_signature, find_similar_examples, search_corpus
---
## Syntax
You modify the object directly in the AOT, in a higher layer. Method override calls `super()`:

```
public void insert()
{
    super();            // run the layer below (NOT `next` — there is no CoC)
    // custom logic
}
```

Pre/post event handlers (AX 2012 R2+) are static methods bound via a delegate or the method's
event nodes: `public static void Foo_post(XppPrePostArgs _args) { ... }`.

## Rules
- **No `[ExtensionOf]`, no `next`** — those are D365 F&O only. AX 2012 uses `super()` and
  overlayering.
- Customizations live in a LAYER (SYS < SYP < GLS < ... < VAR < CUS < USR) and a model within it;
  the highest layer wins. Put ISV code in VAR, partner in CUS, customer in USR.
- Overlayering modifies the object IN PLACE in your layer; an upgrade may conflict and require a
  code merge (this is the cost CoC was invented to remove).
- Element names carry the model prefix.

## Logic
Prefer an event handler when a suitable delegate/event exists (looser coupling, fewer upgrade
conflicts). Otherwise overlayer the method in the lowest acceptable layer. Keep overlayered logic
small and isolated so upgrades merge cleanly.

## Pitfalls
- Writing D365 CoC syntax (`next`, `[ExtensionOf]`) — it does not compile in AX 2012.
- Customizing in too low a layer (SYS) — never; you cannot, and it would be overwritten.
- Heavy overlayering on kernel methods → painful upgrade merges.
