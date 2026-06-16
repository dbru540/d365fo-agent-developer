---
id: event-handler
title: Event handlers (pre/post and delegates)
summary: Extend behaviour at a defined extension point with a static handler — looser-coupled than Chain of Command.
platform: d365fo
object_types: AxClass
grounds: SalesFormLetter, FormRun
example_type: AxClass
example_query: EventHandler
related_topics: coc-extension, form-patterns
related_tools: get_signature, find_similar_examples, search_corpus
---
## Syntax
A handler is a `static` method, usually on a `*_EventHandler` class, bound with an attribute:

```
[PostHandlerFor(classStr(SalesFormLetter), methodStr(SalesFormLetter, run))]
public static void SalesFormLetter_Post(XppPrePostArgs args)
{
    SalesFormLetter sender = args.getThis();
    // read/adjust args, run side effects
}
```

- `[PreHandlerFor(...)]` / `[PostHandlerFor(...)]` wrap a method's entry/exit.
- `[SubscribesTo(classStr(X), delegateStr(X, onSomething))]` subscribes to a published delegate.
- `[DataEventHandler(tableStr(T), DataEventType::Inserting)]` for table events.

## Rules
- The handler is `static` and takes the framework arg type (`XppPrePostArgs`, the delegate's
  declared args, or `DataEventHandlerResult` etc.) — match the exact signature the event expects.
- Pre/post handlers cannot change control flow the way CoC `next` can; for a post handler the
  method already ran. Use the args object to read parameters / set the return value where allowed.
- Subscribe only to PUBLISHED delegates (declared with `delegate`); you cannot invent one.

## Logic
Prefer an event handler over Chain of Command when a suitable delegate/event already exists: it is
looser-coupled and survives signature changes better. Reach for CoC ([[coc-extension]]) when you
must wrap a method end-to-end and no event exposes the moment you need.

## Pitfalls
- Wrong handler signature → it silently never fires (no compile error in some cases).
- Expecting a post handler to prevent the original logic — it ran already; use CoC for that.
- Heavy work in a per-row data event → performance.
