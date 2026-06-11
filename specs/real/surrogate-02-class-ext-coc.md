# [Surrogate] Third-party dimension lookup helper

Family: class-extension with Chain of Command. Reverse-engineered from `BAB-ExportBFC/AxClass/BABDimensionFinancialTag_Extension.xml`.

Artifact Family: class-extension
Model: BAB-ExportBFC
Package: BAB-ExportBFC
Target Object: DimensionFinancialTag
Target Kind: table
Artifact Name: BABDimensionFinancialTag_Extension

## Summary
Add a static helper that performs a form-level lookup over DimensionFinancialTag, filtered to the "ThirdParty" dimension attribute category. Used by form string controls that need a third-party dimension picker.

## Methods
- BABlookupByThirdPartyDimension(FormStringControl _stringControl): public static void

## Acceptance Criteria
- The generated class is an ExtensionOf the DimensionFinancialTag table.
- The generated class exposes the method signature above.
- The body performs SysTableLookup::newParameters on DimensionFinancialTag filtered by DimensionAttribute.findByName('ThirdParty').
