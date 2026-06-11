# D365 F&O / X++ AI Agent Expert Plan

## Goal

Build an AI development system that can work like a senior Dynamics 365 Finance & Operations developer across X++ and AOT artifacts, including classes, tables, forms, menu items, queries, data entities, virtual entities, reports, services, security artifacts, and batch patterns.

The target is not just "teach the model X++." The right target is to build a model-agnostic engineering system around the model so Codex, Claude Code, or Gemini CLI can all use the same D365-specific knowledge, tools, and verification flow.

## Refined Recommendation

The strongest refinement is this: your custom X++ corpus is the main differentiator, and the build environment is mandatory from the MVP stage.

For your situation, the recommended priority order is:

1. Segment and label the code corpus before broad indexing
2. Build the AOT/X++ relationship graph
3. Stand up a real D365 build and validation environment
4. Create benchmark tasks from real historical work
5. Add the multi-agent workflow on top

### What to prioritize first

Before building retrieval or prompting workflows, split the codebase into:

- Standard Microsoft base objects
- Clean custom developments
- Legacy or deprecated code
- ISV packages

This segmentation must drive retrieval ranking and agent behavior. Clean custom developments should become the primary pattern source. Legacy and overlayering-era code can still be indexed, but it should be clearly marked as deprecated so the agent does not reproduce it as a preferred solution.

### Build environment is non-negotiable

The agent will not become reliable without a real compile and validation loop. For D365 F&O, the minimum useful feedback loop is:

- Compile/build
- Best Practice rule checks
- Cross-reference validation
- Packaging
- Validation of entities, security wiring, and reports where feasible

Without this, the system remains a suggestion engine instead of a development platform.

### Refined retrieval stack

The retrieval design should be explicitly hybrid:

- BM25 or keyword search for exact AOT element lookups
- Embeddings for semantic pattern discovery
- Graph traversal for extension chains, references, and security/report/entity relationships

Azure AI Search can be a good orchestration layer if the rest of your platform is already Azure-centered, but it should be treated as an implementation choice, not the core asset. The core asset remains the normalized AOT/X++ graph plus deterministic tools.

### Practical phased scope

A pragmatic rollout is:

- Phase 1: X++/AOT core work such as classes, tables, extensions, CoC, data entities, and OData exposure
- Phase 2: SSRS reports, security artifacts, and benchmark/evaluation automation
- Phase 3: Virtual entities, SysOperation/batch patterns, and a reviewer lane with implementation plus verification agents

These phases should still be adjusted to match your real ticket distribution. If security or reports are a major share of daily work, they should move earlier.

### Merged final recommendation

The right target is not an LLM that knows X++. The right target is a D365 engineering platform composed of:

- Curated historical code
- AOT knowledge graph
- Hybrid retrieval
- D365 build and validation tools
- Benchmark-driven agent workflows
- Persistent memory of accepted and rejected patterns

That is the shortest path to making Codex, Claude Code, or Gemini CLI behave like a senior D365 F&O developer.

## What "Senior Expert" Means in D365 F&O

The agent must understand:

- The real development surface: AOT/Application Explorer objects, X++ classes, tables, views, queries, forms, menu items, labels, EDTs, enums, security artifacts, reports, data entities, services, and SysOperation/batch patterns.
- The current platform constraints: extension-first customization, Chain of Command/event handlers, deployable packages, Azure Pipelines/LCS deployment flow, Best Practice checks, cross references, DB sync, and report generation.
- Integration patterns: public data entities via OData, async data management, custom JSON/SOAP services, and virtual entities through Dataverse.
- That "reports" are split across multiple surfaces: SSRS/AOT development, plus separate Electronic Reporting and financial reporting capabilities.
- Your company patterns and anti-patterns from years of custom development, not only Microsoft documentation.

## Core Principle

Do not try to solve this primarily with fine-tuning.

For D365 F&O, the strongest asset is:

1. Your full source and metadata corpus
2. Strong search and relationship mapping across AOT objects
3. Real compile/build/verification tooling
4. A feedback loop from accepted and rejected changes

RAG plus deterministic tooling plus evaluation will matter more than model tuning for the first serious versions.

## Infrastructure Components

### 1. Vendor-Neutral Agent Layer

Expose the same D365 toolchain to multiple coding agents:

- Codex
- Claude Code
- Gemini CLI

Use a common tool interface such as MCP-style tools or an internal service layer so the D365 knowledge system is independent from the model vendor.

### 2. D365 Knowledge Ingestion Pipeline

Ingest and normalize:

- Microsoft Learn documentation for D365 F&O development
- Official API and integration docs
- Your full source repository
- Standard objects and metadata
- Custom developments created over the years
- Git history
- Pull request reviews and comments
- Work items / tickets / defect descriptions
- Internal development standards and architecture notes
- Deployment notes and incident learnings

### 3. AOT / X++ Knowledge Graph

This is the most important custom component.

Build a normalized graph of D365 elements and their relationships.

For each element, store at least:

- Element type
- Name
- Model
- Package
- Layer / extension relationship
- Base object / extension-of
- References and reverse references
- Related forms, menu items, queries, services, and reports
- Labels
- Security bindings
- Entity properties such as public/OData/data management flags
- Service groups and operations
- Example usages in standard code and custom code

Without this graph, the agent will stay generic and weak.

### 4. Hybrid Retrieval

Use three retrieval modes together:

- Keyword/BM25 search for exact AOT names and technical identifiers
- Embedding search for semantic similarity
- Graph traversal for references, inheritance, extensions, and usage paths

Pure vector search will not be enough for D365 because so much of the work depends on exact symbolic relationships.

### 5. Deterministic Tool Layer

The agent needs tools, not just documents.

Minimum toolset:

- Search element by name/type/model
- Find references / reverse references
- Inspect related AOT objects
- Open similar examples from standard code or custom code
- Build/compile
- Run Best Practice checks
- Run cross-reference generation or validation
- Run SysTest where available
- Create deployable packages
- Inspect OData metadata
- Inspect custom service metadata/endpoints
- Inspect Dataverse virtual entity exposure where relevant

### 6. Evaluation and Learning Store

Persist outcomes for continuous improvement:

- Benchmark tasks
- Accepted patches
- Rejected patches
- Build failures
- Best Practice failures
- Review comments
- Test failures
- Deployment regressions
- Repeated modeling mistakes

This becomes the practical memory of what good D365 development looks like in your organization.

### 7. Rule and Memory Layer

Store explicit organizational guidance such as:

- Preferred extension pattern for a module
- When to use CoC vs event handlers
- Security conventions
- Naming conventions
- Label conventions
- Data entity exposure rules
- Report implementation patterns
- Legacy patterns that must not be copied
- Known unsafe areas and upgrade-sensitive modules

## Important Platform Reality

Based on current Microsoft documentation, runtime APIs are useful but not sufficient for building an expert coding agent.

Inference from the current docs:

- X++ compiles to .NET CIL.
- Best Practice checks are part of the compiler flow, and Microsoft exposes APIs for custom Best Practice rules.
- Public data entities are exposed through OData.
- Finance and operations apps also expose custom services and REST metadata surfaces.
- Virtual entities in Dataverse are built on top of finance and operations entities.

However, a serious coding agent still needs local source and metadata indexing, because runtime service metadata does not replace full AOT understanding.

## Recommended Rollout Plan

### Phase 1: Define Scope

Decide what "expert" means for version 1.

Recommended initial scope:

- X++ classes
- Table extensions
- CoC/event handlers
- Data entities
- Custom services
- Security artifacts
- SysOperation/batch
- SSRS report patterns

Keep out of initial scope if needed:

- Electronic Reporting
- Financial reporting
- Full Power Platform automation
- Full deployment automation to production

### Phase 2: Curate the Corpus

Before using AI broadly:

- Separate Microsoft standard code, custom code, ISV code, and deprecated legacy code
- Mark old patterns that should not be copied
- Tag representative "gold standard" implementations
- Tag common bad examples and why they are bad

This curation step is critical. Otherwise the agent will learn the wrong lessons from years of accumulated code.

### Phase 3: Build the AOT Index and Graph

Create an internal parser/indexer that can produce a searchable store of:

- Objects
- Properties
- Methods
- Extensions
- References
- Labels
- Security relationships
- Report artifacts
- Entities and service surfaces

This becomes the backbone of retrieval.

### Phase 4: Build the Agent Tooling

Add tools that force a strong workflow:

1. Find analogous implementations
2. Explain the intended pattern
3. Generate or modify code
4. Compile
5. Run Best Practice checks
6. Run tests/checks
7. Present patch plus reasoning

Do not allow the agent to skip directly from question to patch without example search and validation.

### Phase 5: Create a Benchmark Suite

Build benchmark tasks by family, for example:

- Add a CoC extension
- Add a table extension field
- Create a data entity
- Publish an entity to OData
- Support a virtual entity scenario
- Create a custom service operation
- Add a privilege/duty/role relationship
- Create or extend an SSRS report
- Add a SysOperation batch class
- Fix a failing build or Best Practice violation

Use these tasks to compare agent versions and prompts.

### Phase 6: Add Review and Critic Workflows

Use one agent for implementation and another for review.

Reviewer responsibilities:

- Check upgrade safety
- Check extension correctness
- Check security impact
- Check performance
- Check naming and labels
- Check data entity behavior
- Check report wiring
- Check test and verification coverage

This is how you reduce hallucinated but plausible-looking D365 code.

### Phase 7: Add Continuous Improvement

After enough real tasks:

- Mine accepted patches
- Mine rejected patches
- Mine reviewer comments
- Add them back into the rule/memory layer
- Refine benchmarks and prompts

Only after this stage should you seriously evaluate fine-tuning.

## Practical MVP Architecture

An effective first system should contain:

- One indexed documentation store for Microsoft Learn and internal docs
- One indexed source mirror for standard and custom D365 artifacts
- One graph/search service for AOT and X++ relationships
- One build-capable development environment the agent can drive
- One benchmark/evaluation pipeline
- One reviewer workflow with persistent memory of accepted and rejected patterns

## What Not to Do First

- Do not start with fine-tuning.
- Do not rely on vector search alone.
- Do not train blindly on all historical code.
- Do not let the system learn deprecated overlayering-era patterns as if they were current best practice.
- Do not couple the architecture to a single model vendor.

## What a Strong Final System Looks Like

The agent should be able to:

- Read a change request
- Find similar implementations in your codebase and in standard objects
- Identify the correct extensibility mechanism
- Propose the right AOT artifacts to create or modify
- Generate code consistent with your standards
- Compile and run checks
- Explain security, entity, report, and deployment impact
- Learn from review feedback over time

At that point, the system is no longer a generic coding assistant. It becomes a D365 F&O engineering platform with AI on top.

## Suggested Next Step

The next practical deliverable should be a technical architecture document with:

- The AOT graph schema
- The ingestion pipeline design
- The exact agent tools to expose
- The benchmark task catalog
- The build and validation workflow
- A 30/60/90-day implementation plan

## Sources

- [Application Explorer](https://learn.microsoft.com/en-us/dynamics365/fin-ops-core/dev-itpro/dev-tools/application-explorer)
- [Commands for determining how elements are used](https://learn.microsoft.com/en-us/dynamics365/fin-ops-core/dev-itpro/dev-tools/element-usage)
- [X++ language reference](https://learn.microsoft.com/en-us/dynamics365/fin-ops-core/dev-itpro/dev-ref/xpp-language-reference)
- [Build and debug projects](https://learn.microsoft.com/en-us/dynamics365/fin-ops-core/dev-itpro/dev-tools/build-debug-project)
- [Write best practice rules](https://learn.microsoft.com/en-us/dynamics365/fin-ops-core/dev-itpro/dev-tools/author-best-practice-rules)
- [Data management and integration by using data entities overview](https://learn.microsoft.com/en-us/dynamics365/fin-ops-core/dev-itpro/data-entities/data-management-integration-data-entity)
- [Service endpoints overview](https://learn.microsoft.com/en-us/dynamics365/fin-ops-core/dev-itpro/data-entities/services-home-page)
- [Custom service development](https://learn.microsoft.com/en-us/dynamics365/fin-ops-core/dev-itpro/data-entities/custom-services)
- [Virtual entities overview](https://learn.microsoft.com/en-us/dynamics365/fin-ops-core/dev-itpro/power-platform/virtual-entities-overview)
- [Create deployable packages in Azure Pipelines](https://learn.microsoft.com/en-us/dynamics365/fin-ops-core/dev-itpro/dev-tools/pipeline-create-deployable-package)
