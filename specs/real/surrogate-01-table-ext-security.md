# [Surrogate] Link BFC account to main account ledger

Family: table-extension + security. Reverse-engineered from `BAB-ExportBFC/AxTableExtension/MainAccount.InterfaceBFC.xml` + `AxSecurityPrivilege/BABBFCAccount.xml`.

## Artifact
Artifact Id: maintable-ext
Artifact Family: table-extension
Model: BAB-ExportBFC
Package: BAB-ExportBFC
Target Object: MainAccount

### Summary
Extend the MainAccount table so that each general-ledger main account can carry its BFC (consolidation) accounting layer and link to a BFC account reference.

### Fields
- BABBFCAccountLayer: OperationsTax
- BABBFCAccount: BABBFCAccountRecId

## Artifact
Artifact Id: bfc-privilege
Artifact Family: security-privilege
Model: BAB-ExportBFC
Package: BAB-ExportBFC
Artifact Name: BABBFCAccount
Label: @BABExportBFC:BFCLedgerAccount

### Summary
Grant create/read/update/delete access to the BFC account maintenance menu item.

### Entry Points
- MenuItemDisplay:BABBFCAccount
