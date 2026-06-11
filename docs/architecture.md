# Architecture

## Goal

Turn a real D365 F&O repository into a deterministic knowledge surface that coding agents can use to generate D365 artifacts from a specification.

The current implementation is the local foundation for that platform. It is not the final Azure deployment yet, but it already enforces the first important boundary: corpus curation and metadata extraction are separate from generation, and compile/deploy concerns are downstream of spec-to-code.

## Current Implemented Components

### 1. Corpus Rules

`config/babiloufinops.rules.json` is the pilot classification policy for the sample client repo.

- Default classification: `custom-canonical`
- Known ISV/reference models: `BHSLicenseBase`, `CDC`, `CDI`, `CLI`, `EBEssentials`, `EBImportMedia`, `EBResources`, `EBSearchMedia`
- Legacy paths can be down-ranked with `path_contains` rules

This makes retrieval ranking explicit instead of letting the model infer quality from raw volume.

### 2. Local Metadata Indexer

`src/d365fo_agent/indexer.py` scans `src/xplusplus/models` and builds an in-memory catalog from:

- model descriptors
- AOT XML artifacts
- `.xref` archives

The indexer extracts:

- artifact name, type, model, package, label, path, classification
- public entity exposure and data-management flags
- extension targets for classes and table extensions
- related tables from table extensions
- security entry points from privileges
- report provider bindings from report datasets
- reverse references from `.xref` files

### 3. Deterministic CLI Tool Surface

`src/d365fo_agent/cli.py` exposes the initial local tool contracts:

- `inventory`
- `find-element`
- `get-element-details`
- `find-references`
- `find-reverse-references`
- `analyze-spec`
- `generate-from-spec`
- `build-project`

This is the first implementation of the future MCP-style tool layer. The commands are local and JSON-based now, but the contracts are shaped so they can move behind an HTTP/MCP boundary later.

### 4. Specification-to-Code Layer

`src/d365fo_agent/specs.py` and `src/d365fo_agent/generator.py` implement the first spec-driven generation path.

The flow is:

- parse a structured Markdown or plain-text specification
- build an artifact plan for a supported family
- retrieve the most relevant examples from the indexed repo
- generate candidate D365 artifact XML into a chosen output directory

Supported families in the current slice:

- `table-extension`
- `class-extension`
- `data-entity`
- `security-privilege`

### 5. Build Adapter Scaffold

`src/d365fo_agent/build.py` wraps `AXModulesBuild.proj` command planning.

The adapter does two things today:

- prepares a deterministic MSBuild command with explicit output properties
- leaves execution optional so local development does not depend on a configured D365 build VM

This is the correct seam for later Azure DevOps and Windows build-agent integration, but it is intentionally secondary to the spec-to-code loop.

## Target Azure-First Topology

The approved MVP direction remains Azure-first:

- `Azure Database for PostgreSQL Flexible Server` for metadata, relations, rules, benchmark, and learning tables
- `Azure Container Apps` for tool APIs, retrieval APIs, indexing workers, and review services
- `Azure Service Bus` for indexing and build job orchestration
- `Azure DevOps` plus a `self-hosted Windows agent` for D365 build, Best Practice checks, packaging, and cross-reference validation
- `Azure Monitor / Log Analytics` for operational telemetry

## Near-Term Delivery Shape

### Local slice implemented now

- repo-aware classification
- metadata and relation extraction
- xref-backed reverse references
- JSON CLI contracts
- spec parsing and artifact planning
- example-bundle construction from the client repo
- deterministic generation for a first set of D365 artifact families
- build command adapter

### Next service slice

- persist catalog output into PostgreSQL
- expose the same commands as service endpoints
- add relation-backed search policies and ranking
- normalize generated-artifact runs and later build results into stored records

### Later review slice

- reviewer lane over generated patches
- benchmark execution records
- accepted/rejected pattern memory

## Constraints

- No new runtime dependencies were introduced in this slice.
- Real compile, Best Practice, and packaging verification still require the Windows D365 build environment.
- `.xref` parsing is implemented from the zipped UTF-16 payload already present in the repo; no proprietary binary reverse-engineering was needed.
