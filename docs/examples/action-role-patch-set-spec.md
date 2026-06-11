# Add asset journal processing access

## Artifact
Artifact Id: asset-action
Artifact Family: menu-item-action
Model: BABAccountsPayable
Package: BABAccountsPayable
Artifact Name: BABAssetJournalProcess
Target Object: BABAssetJournalProcessService
Target Kind: class
Label: @BABAccountsPayable:AssetJournalProcess

## Artifact
Artifact Id: asset-privilege
Artifact Family: security-privilege
Model: BABAccountsPayable
Package: BABAccountsPayable
Artifact Name: BABAssetJournalProcessPrivilege

### Entry Points
- ref:asset-action

## Artifact
Artifact Id: asset-duty
Artifact Family: security-duty-extension
Model: BABAccountsPayable
Package: BABAccountsPayable
Target Object: AssetAccountingMaintain

### Privileges
- ref:asset-privilege

## Artifact
Artifact Id: asset-role
Artifact Family: security-role-extension
Model: BABAccountsPayable
Package: BABAccountsPayable
Target Object: AssetAccountingManager

### Duties
- AssetAccountingMaintain

### Privileges
- ref:asset-privilege
