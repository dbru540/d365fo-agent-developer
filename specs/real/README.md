# Real-Ticket Specs (Phase A2)

This folder holds Markdown specs translated from real historical tickets, used to validate the spec-to-code pipeline end-to-end before adding more generator surfaces.

## Conventions

- One Markdown file per ticket: `<ticket-id>.md` (e.g., `BAB-1234.md`, `ADO-5678.md`).
- Use the contract in `docs/specification-contract.md`. Start with a title line, then `Key: Value` metadata, then `## Summary` / `## Fields` / `## Methods` / etc.
- Multi-artifact tickets use repeated `## Artifact` blocks. Use `Artifact Id` + `ref:<id>` to wire artifacts together.

## Target mix (one per family)

1. `table-extension + security` patch-set
2. `class-extension` with Chain of Command
3. `data-entity`
4. `service` or `service-group`
5. `form-extension`

## Running a ticket

```bash
cd <repo-root>
PYTHONPATH=src python -m d365fo_agent.cli analyze-spec \
  --repo-root D365_repo/BabilouFinOps \
  --rules config/babiloufinops.rules.json \
  --spec specs/real/<ticket-id>.md

PYTHONPATH=src python -m d365fo_agent.cli generate-from-spec \
  --repo-root D365_repo/BabilouFinOps \
  --rules config/babiloufinops.rules.json \
  --spec specs/real/<ticket-id>.md \
  --output-dir .omx/verify-real-<ticket-id>
```

## Scoring per ticket (log to `.omx/gap-log.md`)

For each ticket, grade on 4 axes and classify the top failure mode:

- **Family planning** — did `analyze-spec` pick the right artifact family (and in a patch-set, the right set)?
- **Retrieval quality** — do the surfaced `examples` actually resemble what the agent needs? Does `graph_examples` add signal?
- **Merge safety** — if the target file already exists, is the merge non-destructive and correct?
- **XML plausibility** — does a senior D365 developer accept the generated XML on eyeball review (naming, labels, permissions, wiring)?

Gap types to tag in the log:
- `retrieval-miss` — examples irrelevant to the spec
- `merge-conflict` — merge dropped/duplicated structure
- `missing-family` — the family needed does not yet exist in the generator
- `bad-label` — label or string mismatch with repo convention
- `wiring-hole` — `ref:` resolved incorrectly or dependency not followed
- `other` — describe inline
