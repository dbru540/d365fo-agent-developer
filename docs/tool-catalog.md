# Tool Catalog

## Purpose

These are the deterministic tool contracts exposed by the current local implementation. They are intentionally agent-friendly and JSON-based so they can move into MCP or HTTP services without changing the logical contract.

## Implemented Commands

### `inventory`

Summarize the indexed repo.

Example:

```powershell
$env:PYTHONPATH='src'
python -m d365fo_agent.cli inventory `
  --repo-root .\D365_repo\BabilouFinOps `
  --rules .\config\babiloufinops.rules.json
```

Output:

- model count
- artifact count
- classification summary

### `find-element`

Find artifacts by name with optional artifact-type narrowing.

Example:

```powershell
$env:PYTHONPATH='src'
python -m d365fo_agent.cli find-element `
  --repo-root .\D365_repo\BabilouFinOps `
  --rules .\config\babiloufinops.rules.json `
  --name BABCheque_BOA
```

Returns matching artifacts with model, package, type, classification, label, and path.

### `get-element-details`

Return the best matching artifact plus inbound and outbound relations already known in the catalog.

Use it after `find-element` when the agent needs context before editing or reviewing code.

### `find-references`

Raw text lookup across XML artifacts.

This is the broad fallback when graph relations are not enough.

### `find-reverse-references`

Use `.xref` relations to answer “what calls or references this symbol?”

This is safer than pure text search for runtime and metadata call paths because it relies on model-produced cross references.

### `analyze-spec`

Parse a specification, infer the output artifact plan, and attach the most relevant repo examples.

Use it before generation when the agent needs a grounded package of:

- parsed metadata
- target artifact family and output path
- one or more artifact plans for a multi-artifact spec
- resolved dependencies for a patch set
- example artifacts and source XML

### `generate-from-spec`

Generate candidate D365 artifact XML from a structured specification.

Current behavior:

- parses the spec
- builds one or more artifact plans
- resolves `ref:<artifact-id>` wiring across artifact blocks
- retrieves relevant examples for each planned artifact
- writes one or more generated XML files
- merges into existing repo artifacts for supported families
- writes `generation-bundle.json`
- writes `generation-manifest.json`

Current patch-set coverage includes:

- navigation artifacts: `menu-item-display`, `menu-item-action`, `menu-item-output`
- access artifacts: `security-privilege`, `security-duty-extension`, `security-role-extension`
- UI/data artifacts: `form-extension`, `query`
- integration artifacts: `service`, `service-group`

The generation manifest now includes `artifact_results` with per-file `generation_mode` values such as `created` or `merged`.

This is the current primary workflow for spec-driven code generation.

### `build-project`

Prepare or execute a deterministic MSBuild command around `AXModulesBuild.proj`.

Current usage:

- local planning without execution
- future handoff point for Azure DevOps and the Windows D365 build host

## Target Tool Surface

The plan-approved service catalog is larger than the local slice. These commands are the next logical additions:

- `find_similar_examples`
- `get_extension_chain`
- `get_security_links`
- `get_entity_exposure`
- `get_report_bindings`
- `run_best_practice_checks`
- `run_cross_reference_validation`
- `create_deployable_package`
- `get_build_errors`

## Contract Principles

- Specification analysis happens before generation.
- Retrieval happens before generation.
- Exact or graph-backed results outrank semantic guesses.
- Every tool response should include enough structured metadata to cite evidence in a coding or review step.
- Build-related commands must preserve the exact command line and exit status for auditability.
