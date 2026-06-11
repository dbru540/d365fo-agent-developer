# 30 / 60 / 90 Day Rollout

## First 30 Days

- Lock the pilot corpus around `D365_repo/Contoso`
- Review and refine `config/contoso.rules.json` with domain owners
- Persist the current local catalog into PostgreSQL-backed storage
- Add repo-level inventory exports and artifact snapshots to the ingestion workflow
- Assemble the first 10 benchmark cases from real project history

## First 60 Days

- Move the local CLI contracts behind service endpoints
- Add `get_security_links`, `get_entity_exposure`, and `get_report_bindings` as first-class service tools
- Wire `build-project` into Azure DevOps plus the Windows D365 build host
- Normalize build, Best Practice, and packaging results into stored run records
- Pilot the toolkit on a small set of real development or review tasks

## First 90 Days

- Add reviewer-lane automation over generated changes
- Store accepted and rejected patterns in the learning store
- Add benchmark run history and retrieval-quality scoring
- Expand classification rules for legacy/deprecated areas identified during pilot use
- Decide whether semantic search is needed beyond exact and graph-backed retrieval

## Exit Criteria for the MVP Pilot

- The corpus is segmented and review-approved.
- Exact lookup and xref-backed reverse references are reliable on the pilot repo.
- Security and report artifacts are retrievable alongside core X++ artifacts.
- A build request can be handed to the Windows D365 environment deterministically.
- Benchmark outcomes can be compared across retrieval or prompt changes.

