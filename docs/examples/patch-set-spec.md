# Add asset journal maintenance access

## Artifact
Artifact Id: asset-menu
Artifact Family: menu-item-display
Model: BABAccountsPayable
Package: BABAccountsPayable
Artifact Name: BABAssetJournalLink
Target Object: BABAssetJournalLinkForm
Target Kind: form
Label: @BABAccountsPayable:AssetJournalLink

### Summary
Add a display menu item for the asset journal link form.

## Artifact
Artifact Id: asset-privilege
Artifact Family: security-privilege
Model: BABAccountsPayable
Package: BABAccountsPayable
Artifact Name: BABAssetJournalLinkPrivilege

### Summary
Grant access to the asset journal link menu item.

### Entry Points
- ref:asset-menu

## Artifact
Artifact Id: asset-duty
Artifact Family: security-duty-extension
Model: BABAccountsPayable
Package: BABAccountsPayable
Target Object: AssetAccountingMaintain

### Summary
Add the new privilege into the maintenance duty.

### Privileges
- ref:asset-privilege
