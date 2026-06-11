# Add asset journal linkage support

## Artifact
Artifact Family: table-extension
Model: BABAccountsPayable
Package: BABAccountsPayable
Target Object: AssetTable

### Summary
Store the related ledger journal transaction recid on the asset.

### Fields
- BABLedgerJournalTransRecId: RefRecId

## Artifact
Artifact Family: class-extension
Model: BABAccountsPayable
Package: BABAccountsPayable
Target Object: AssetTable
Artifact Name: BABAssetTable_Extension
Target Kind: table

### Summary
Add a delete extension stub around asset deletion.

### Methods
- delete(): public void
