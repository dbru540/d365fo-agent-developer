# Benchmark Catalog

## Purpose

These benchmark families turn the client repo into a measurable pilot instead of a vague demo corpus.

The cases below are grounded in the current repository structure under `D365_repo/Contoso`.

## Approved Benchmark Families

### 1. Class Extension

- Goal: detect and retrieve a class or table extension pattern
- Representative source: `src/xplusplus/models/BABAccountsPayable/BABAccountsPayable/AxClass/BABAssetTable_Extension.xml`
- Success criteria:
  - inventory includes the artifact
  - `extension-of` resolves to `AssetTable`
  - reverse references remain queryable from `.xref`

### 2. Table Extension

- Goal: detect custom fields and table relations on an extension
- Representative source: `src/xplusplus/models/BABAccountsPayable/BABAccountsPayable/AxTableExtension/AssetTable.BABAccountsPayable.xml`
- Success criteria:
  - extension target resolves to `AssetTable`
  - related table resolves to `LedgerJournalTrans`
  - classification remains `custom-canonical`

### 3. Public Data Entity

- Goal: extract entity exposure metadata for OData and data management
- Representative source: `src/xplusplus/models/BABAccountsPayable/BABAccountsPayable/AxDataEntityView/BABDetailledVendInvoiceDataAreaEntity.xml`
- Success criteria:
  - `is_public = true`
  - `data_management_enabled = true`
  - `public_entity_name` and `public_collection_name` are indexed

### 4. Security Privilege

- Goal: map privileges to secured entry points
- Representative source: `src/xplusplus/models/BAB-ExportBFC/BAB-ExportBFC/AxSecurityPrivilege/BABBFCAccount.xml`
- Success criteria:
  - privilege is indexed as `AxSecurityPrivilege`
  - `secured-by` relation resolves to `MenuItemDisplay:BABBFCAccount`
  - label reference is preserved

### 5. SSRS Report Binding

- Goal: discover report/provider linkage from report metadata
- Representative source: `src/xplusplus/models/BABAccountsPayable/BABAccountsPayable/AxReport/BABCheque_BOA.xml`
- Success criteria:
  - report is indexed as `AxReport`
  - provider link resolves to `BABChequeDP_BOA`
  - report artifacts are included in phase-1 retrieval

### 6. Project-to-Task Traceability

- Goal: map benchmark candidates back to historical delivery units
- Representative sources:
  - `src/xplusplus/projects/Fiveforty/121649-EcolCustomerResearch/...`
  - `src/xplusplus/projects/Fiveforty/145293_BABLedgertransSettlementEntity/...`
  - `src/xplusplus/projects/Fiveforty/CustomerEvents/...`
- Success criteria:
  - benchmark definitions can cite a concrete project lineage
  - at least 10 historical tasks can be assembled for pilot evaluation

## Benchmark Execution Rules

- Use the sample repo as the first pilot corpus.
- Prefer cases that have both metadata artifacts and project history.
- Keep one benchmark per behavior family; do not merge unrelated concerns into the same case.
- Treat build-capable execution as a separate verification stage once the Windows D365 agent is available.

