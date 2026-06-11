# [Surrogate] Public data entity for BFC accounts

Family: data-entity. Reverse-engineered from `BAB-ExportBFC/AxDataEntityView/BABBFCAccountEntity.xml`.

Artifact Family: data-entity
Model: BAB-ExportBFC
Package: BAB-ExportBFC
Artifact Name: BABBFCAccountEntity
Public Entity Name: Account
Public Collection Name: Accounts
Label: @BABExportBFC:BFCLedgerAccount

## Summary
Expose the BABBFCAccount custom table as a public OData data entity named Account. Enable data management and provide AccountNum and Name as mapped fields.

## Fields
- AccountNum: AccountNum from BABBFCAccount
- Name: Name from BABBFCAccount

## Acceptance Criteria
- IsPublic = Yes, DataManagementEnabled = Yes.
- PublicEntityName = Account, PublicCollectionName = Accounts.
- Mapped fields wire to the BABBFCAccount datasource.
