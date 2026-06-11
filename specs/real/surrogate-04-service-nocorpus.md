# [Surrogate] Hypothetical BFC export service

Family: service. This ticket deliberately has **no custom corpus precedent** — no BAB*/Fiveforty*/FLexmind* services exist in the repo. Used to measure retrieval behavior under the "no-example-in-custom-code" scenario.

Artifact Family: service
Model: BAB-ExportBFC
Package: BAB-ExportBFC
Artifact Name: BABBFCExportService
Service Class: BABBFCExportServiceClass

## Operations
- exportBFCAccounts|exportBFCAccounts
- validateBFCExportPayload|validateBFCExportPayload

## Acceptance Criteria
- Generated AxService binds Class = BABBFCExportServiceClass.
- Both operations exposed under Operations.
