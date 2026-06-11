# Specification Contract

## Purpose

The current generator works from structured Markdown or plain-text specifications.

The goal is not to force a heavy template. The goal is to make the minimum information explicit so the system can:

- identify the target artifact family
- build the output path
- retrieve similar examples
- generate candidate D365 artifact XML

## Supported Families

- `table-extension`
- `class-extension`
- `data-entity`
- `form-extension`
- `menu-item-action`
- `menu-item-display`
- `menu-item-output`
- `query`
- `service`
- `service-group`
- `security-privilege`
- `security-duty-extension`
- `security-role-extension`

The contract supports:

- a single artifact spec
- a multi-artifact spec with repeated `## Artifact` blocks
- a patch-set style multi-artifact spec with `Artifact Id` plus `ref:<artifact-id>` wiring
- merge/edit generation when the planned output path already exists in the repo

## Required Metadata

Use `Key: Value` lines near the top of the spec.

Required keys for all specs:

- `Artifact Family`
- `Model`

Common optional keys:

- `Artifact Id`
- `Package`
- `Target Object`
- `Target Kind`
- `Artifact Name`
- `Label`
- `Configuration Key`
- `Linked Permission Object`
- `Linked Permission Object Child`
- `Linked Permission Type`
- `Service Class`
- `Auto Deploy`
- `Public Entity Name`
- `Public Collection Name`

## Supported Sections

Use Markdown headings for the behavioral details.

- `## Summary`
- `## Fields`
- `## Methods`
- `## Controls`
- `## Entry Points`
- `## Operations`
- `## Services`
- `## Privileges`
- `## Duties`
- `## Acceptance Criteria`

The parser reads bullet items and plain lines inside those sections.

## Example: Table Extension

```md
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
```

## Example: Class Extension

```md
# Add delete override for asset table

Artifact Family: class-extension
Model: BABAccountsPayable
Package: BABAccountsPayable
Target Object: AssetTable
Artifact Name: BABAssetTable_Extension
Target Kind: table

## Summary
Add a chain of command extension around delete.

## Methods
- delete(): public void
```

## Example: Form Extension

```md
# Add asset link control to asset table form

Artifact Family: form-extension
Model: BABAccountsPayable
Package: BABAccountsPayable
Target Object: AssetTable
Artifact Name: AssetTable.BABAccountsPayable

## Controls
- String:BABAssetLink|AssetTable|BABAssetLink|Identification
```

Control format:

`ControlType:ControlName|DataSource|DataField|Parent`

Current control types:

- `String`
- `CheckBox`
- `ComboBox`

## Example: Security Privilege

```md
# Add privilege for BFC account maintenance

Artifact Family: security-privilege
Model: BAB-ExportBFC
Package: BAB-ExportBFC
Artifact Name: BABBFCAccountMaintain

## Entry Points
- MenuItemDisplay:BABBFCAccount
```

## Example: Menu Item Display

```md
# Add asset journal display item

Artifact Family: menu-item-display
Model: BABAccountsPayable
Package: BABAccountsPayable
Artifact Name: BABAssetJournalLink
Target Object: BABAssetJournalLinkForm
Target Kind: form
Label: @BABAccountsPayable:AssetJournalLink
```

## Example: Menu Item Action

```md
# Add asset journal process action

Artifact Family: menu-item-action
Model: BABAccountsPayable
Package: BABAccountsPayable
Artifact Name: BABAssetJournalProcess
Target Object: BABAssetJournalProcessService
Target Kind: class
Label: @BABAccountsPayable:AssetJournalProcess
```

## Example: Menu Item Output

```md
# Add asset journal output menu item

Artifact Family: menu-item-output
Model: BABAccountsPayable
Package: BABAccountsPayable
Artifact Name: BABAssetJournalOutput
Target Object: BABAssetJournalController
Target Kind: class
Label: @BABAccountsPayable:AssetJournalOutput
Linked Permission Object: AssetJournalReport
Linked Permission Object Child: Report
Linked Permission Type: SSRSReport
Configuration Key: Asset
```

## Example: Query

```md
# Add asset journal query

Artifact Family: query
Model: BABAccountsPayable
Package: BABAccountsPayable
Artifact Name: BABAssetJournalQuery
Root Data Source: AssetTable
Root Table: AssetTable
Allow Cross Company: Yes
Order By: AssetId
```

## Example: Service

```md
# Add asset journal service

Artifact Family: service
Model: BABAccountsPayable
Package: BABAccountsPayable
Artifact Name: BABAssetJournalService
Service Class: BABAssetJournalServiceClass

## Operations
- getAssetJournalLink|getAssetJournalLink
```

Operation format:

`OperationName|MethodName`

## Example: Service Group

```md
# Add asset journal service group

Artifact Family: service-group
Model: BABAccountsPayable
Package: BABAccountsPayable
Artifact Name: BABAssetJournalServiceGroup
Auto Deploy: Yes

## Services
- BABAssetJournalService
```

## Example: Security Duty Extension

```md
# Add privilege to a duty

Artifact Family: security-duty-extension
Model: BABAccountsPayable
Package: BABAccountsPayable
Target Object: AssetAccountingMaintain

## Privileges
- BABAssetJournalLinkPrivilege
```

## Example: Security Role Extension

```md
# Add privilege to a role

Artifact Family: security-role-extension
Model: BABAccountsPayable
Package: BABAccountsPayable
Target Object: AssetAccountingManager

## Privileges
- BABAssetJournalLinkPrivilege

## Duties
- AssetAccountingMaintain
```

## Example: Multi-Artifact Spec

Use repeated `## Artifact` blocks, with per-artifact details under `###` headings.

```md
# Add asset journal linkage support

## Artifact
Artifact Family: table-extension
Model: BABAccountsPayable
Package: BABAccountsPayable
Target Object: AssetTable

### Fields
- BABLedgerJournalTransRecId: RefRecId

## Artifact
Artifact Family: class-extension
Model: BABAccountsPayable
Package: BABAccountsPayable
Target Object: AssetTable
Artifact Name: BABAssetTable_Extension
Target Kind: table

### Methods
- delete(): public void
```

## Example: Patch Set With Wiring

Use `Artifact Id` and `ref:<artifact-id>` when one generated artifact should depend on another.

```md
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

## Artifact
Artifact Id: asset-privilege
Artifact Family: security-privilege
Model: BABAccountsPayable
Package: BABAccountsPayable
Artifact Name: BABAssetJournalLinkPrivilege

### Entry Points
- ref:asset-menu

## Artifact
Artifact Id: asset-duty
Artifact Family: security-duty-extension
Model: BABAccountsPayable
Package: BABAccountsPayable
Target Object: AssetAccountingMaintain

### Privileges
- ref:asset-privilege
```

## Example: Action + Role Patch Set

```md
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
```

## Example: Service Patch Set

```md
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
```

## Notes

- If `Package` is omitted, it defaults to `Model`.
- `Artifact Id` is optional unless another artifact needs to reference that block.
- For `table-extension`, `Target Object` is required.
- For `class-extension`, `Target Object` is required and `Artifact Name` is recommended.
- For `data-entity`, either `Artifact Name` or `Public Entity Name` must be provided.
- For `form-extension`, `Target Object` is the base form name and controls are declared in `## Controls`.
- For `menu-item-action`, `Target Object` is the backing class/form/query and `Target Kind` controls `<ObjectType>`.
- For `menu-item-display`, `Target Object` is the underlying form or object name.
- For `menu-item-output`, `Target Object` is the backing object and linked-permission metadata is optional but supported.
- For `query`, the current generator supports one simple root datasource plus optional `Allow Cross Company` and `Order By`.
- For `service`, `Service Class` defines the backing class and `## Operations` defines exposed operations.
- For `service-group`, `## Services` lists service names or `ref:<artifact-id>` references and `Auto Deploy` is optional.
- For `security-duty-extension`, `Target Object` is the base duty name.
- For `security-role-extension`, `Target Object` is the base role name.
- `Target Kind` defaults to `table` for class extensions.
- In multi-artifact specs, metadata under each `## Artifact` block applies only to that artifact.
- `ref:<artifact-id>` is resolved during planning, so generated privileges and entry points can wire to generated artifacts without repeating names.
- For supported families, if the target file already exists under the repo root, generation runs in merge mode instead of replacing the artifact with a blank scaffold.

## Current Merge Coverage

- `table-extension`: appends missing fields and preserves existing relations and metadata
- `class-extension`: appends missing methods and preserves existing declaration and methods
- `menu-item-display`, `menu-item-action`, `menu-item-output`: updates scalar properties on existing menu items
- `security-privilege`: appends missing entry points
- `security-duty-extension`: appends missing privilege references
- `security-role-extension`: appends missing duty and privilege references
- `form-extension`: appends missing extension controls
- `query`: updates cross-company and root datasource metadata and appends missing order-by fields
- `service`: appends missing operations
- `service-group`: appends missing service references and updates `AutoDeploy`
