# Add ledger journal reference to asset records

Artifact Family: table-extension
Model: BABAccountsPayable
Package: BABAccountsPayable
Target Object: AssetTable

## Summary
Add a custom field that stores the related ledger journal transaction recid.

## Fields
- BABLedgerJournalTransRecId: RefRecId

## Acceptance Criteria
- The generated artifact extends AssetTable.
- The artifact contains the BABLedgerJournalTransRecId field.
