# [Surrogate] BFC export group on MainAccount form

Family: form-extension. Reverse-engineered from `BAB-ExportBFC/AxFormExtension/MainAccount.InterfaceBFC.xml`.

Artifact Family: form-extension
Model: BAB-ExportBFC
Package: BAB-ExportBFC
Target Object: MainAccount
Artifact Name: MainAccount.InterfaceBFC

## Summary
Add a "BFC Export" control group to the MainAccount form's General tab exposing the BABBFCAccountLayer combobox and a reference-group control for the BABBFCAccount foreign key.

## Controls
- ComboBox:BABBFCExport_BABBFCAccountLayer|MainAccount|BABBFCAccountLayer|GeneralTabGroup
- String:BABBFCExport_BABBFCAccount|MainAccount|BABBFCAccount|GeneralTabGroup

## Acceptance Criteria
- Generated AxFormExtension extends MainAccount.
- Both controls anchored under the General tab.
