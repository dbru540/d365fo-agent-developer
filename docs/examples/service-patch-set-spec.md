# Add asset journal service integration

## Artifact
Artifact Id: asset-service
Artifact Family: service
Model: BABAccountsPayable
Package: BABAccountsPayable
Artifact Name: BABAssetJournalService
Service Class: BABAssetJournalServiceClass

### Operations
- getAssetJournalLink|getAssetJournalLink

## Artifact
Artifact Id: asset-service-group
Artifact Family: service-group
Model: BABAccountsPayable
Package: BABAccountsPayable
Artifact Name: BABAssetJournalServiceGroup
Auto Deploy: Yes

### Services
- ref:asset-service
