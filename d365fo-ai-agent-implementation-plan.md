# D365 F&O / X++ AI Agent Implementation Plan

## Purpose

This document turns the D365 F&O AI agent strategy into a concrete implementation plan.

The objective is to build an AI-assisted engineering platform that can help Codex, Claude Code, or Gemini CLI work like a senior D365 F&O developer by combining:

- Curated D365 source and metadata
- AOT-aware indexing and relationship mapping
- Deterministic build and validation tools
- Retrieval and memory services
- A benchmark and review pipeline

## Target Outcome

At the end of the MVP, the agent should be able to:

- Understand D365 AOT artifacts and relationships
- Find similar patterns in standard and custom code
- Propose the correct extensibility mechanism
- Generate or modify X++ and related artifacts
- Validate changes through build and checks
- Improve over time using accepted and rejected outcomes

## Phase 1 Scope

Recommended MVP scope:

- X++ classes
- Tables and table extensions
- Chain of Command extensions
- Event handlers
- Data entities
- OData exposure
- Security basics
- Optional SSRS support if it is part of frequent daily work

Out of scope for the initial MVP unless required:

- Electronic Reporting
- Financial reporting
- Full Power Platform automation
- Advanced deployment orchestration to production

## Implementation Principles

- Extension-first only
- Exact lookup before semantic lookup
- Retrieval before generation
- Build and validation before accepting output
- Use your custom codebase as the primary pattern source
- Treat deprecated or legacy code as reference-only unless explicitly approved
- Keep the architecture model-agnostic

## Required Inputs

The implementation requires:

- D365 source tree with custom models
- Standard or reference source where legally and practically available
- AOT metadata files
- Labels
- Git history
- Access to build-capable D365 environment
- Access to Azure DevOps or equivalent CI system
- A sample set of real historical development tasks

## Workstream Overview

The implementation is divided into six workstreams:

1. Corpus segmentation and curation
2. Metadata extraction and graph building
3. Search and retrieval services
4. Agent tool layer
5. Build and validation integration
6. Benchmarking, review, and continuous learning

## Workstream 1: Corpus Segmentation and Curation

### Goal

Separate the codebase into quality tiers and usage classes before indexing.

### Inputs

- Standard Microsoft artifacts
- Custom company developments
- ISV artifacts
- Legacy or deprecated code

### Outputs

- Classification manifest for each model/package/path
- Tags such as:
  - `standard-reference`
  - `custom-canonical`
  - `legacy-deprecated`
  - `isv-reference`
- Initial allow/avoid rules for retrieval ranking

### Tasks

- Build a path and model inventory
- Assign classification labels
- Mark known deprecated patterns
- Identify gold-standard implementations
- Identify known bad examples

## Workstream 2: Metadata Extraction and Graph Building

### Goal

Create a normalized AOT/X++ metadata index and relationship graph.

### Core Entities

The metadata model should represent:

- Classes
- Methods
- Tables
- Table extensions
- Forms
- Menu items
- Queries
- Views
- Data entities
- Services
- Security artifacts
- Reports
- Labels
- Models
- Packages

### Core Relationships

- `extends`
- `extension-of`
- `references`
- `used-by`
- `called-by`
- `belongs-to-model`
- `belongs-to-package`
- `secured-by`
- `exposed-as-entity`
- `exposed-as-service`
- `related-to-report`
- `uses-label`

### Technical Output

Produce:

- Normalized metadata tables
- A relationship graph
- Searchable symbol records
- Reverse-reference records
- Artifact lineage across models and extensions

## Workstream 3: Search and Retrieval Services

### Goal

Provide reliable retrieval that matches how D365 developers actually work.

### Retrieval Modes

- Exact search for object names and identifiers
- Full-text search for code and metadata
- Semantic search for analogous patterns
- Graph traversal for relationship-based lookup

### Recommended Retrieval Policy

- First pass: exact search
- Second pass: graph expansion from known symbols
- Third pass: semantic pattern search

### Suggested Technology Options

- Metadata store: PostgreSQL or Azure SQL
- Graph layer: Neo4j or graph-oriented relational schema
- Full-text search: PostgreSQL full-text or Azure AI Search
- Optional vectors: pgvector or Azure AI Search vector support

The vector layer is optional in the first MVP and should not be the source of truth.

## Workstream 4: Agent Tool Layer

### Goal

Expose D365-specific capabilities as deterministic tools that any coding agent can call.

### Minimum Tool Catalog

- `find_element`
- `get_element_details`
- `find_references`
- `find_reverse_references`
- `find_similar_examples`
- `get_extension_chain`
- `get_security_links`
- `get_entity_exposure`
- `get_report_bindings`
- `build_project`
- `run_best_practice_checks`
- `run_cross_reference_validation`
- `create_deployable_package`
- `get_build_errors`

### Expected Agent Workflow

For a normal development request, the agent should:

1. Identify the artifact family involved
2. Retrieve similar implementations
3. Inspect related references and extensions
4. Propose the implementation approach
5. Generate or modify code
6. Build and validate
7. Present output and evidence

## Workstream 5: Build and Validation Integration

### Goal

Make the agent verifiable, not just generative.

### Required Validation Loop

- Compile/build
- Best Practice rule execution
- Cross-reference validation
- Packaging
- Targeted validation for:
  - entities
  - security artifacts
  - reports

### Infrastructure Need

Provide one D365 build-capable environment accessible to the implementation pipeline.

This may be:

- A dedicated build VM
- A self-hosted agent
- A controlled internal build host integrated with Azure DevOps

## Workstream 6: Benchmarking, Review, and Continuous Learning

### Goal

Continuously improve the system using real outcomes.

### Benchmark Task Families

- Add CoC extension
- Add event handler
- Add table extension field
- Create or extend data entity
- Expose entity via OData
- Add service operation
- Add security artifacts
- Create or extend SSRS artifacts
- Add SysOperation batch implementation
- Fix failing build or Best Practice issue

### Review Lane

Use a separate reviewer workflow to validate:

- Extensibility correctness
- Upgrade safety
- Security correctness
- Performance risks
- Naming and label compliance
- Entity and service correctness
- Report wiring correctness

### Learning Inputs

Persist and classify:

- Accepted patches
- Rejected patches
- Build failures
- Review comments
- Repeated mistakes
- Successful resolution patterns

## Azure Hosting Architecture

This option is the best fit if the organization is already strongly Azure-oriented and wants managed services where possible.

### Recommended Components

- `Azure Database for PostgreSQL Flexible Server`
  - Primary metadata store
  - Graph edge tables
  - Rules and memory tables
  - Optional `pgvector` for embeddings
- `Azure Blob Storage`
  - Source snapshots
  - Exported metadata
  - Documents
  - Build artifacts
  - Logs
- `Azure Container Apps`
  - MCP-style tool APIs
  - Retrieval services
  - Indexing workers
  - Evaluation services
- `Azure Service Bus`
  - Background job queue
  - Build request orchestration
  - Indexing and evaluation jobs
- `Azure DevOps`
  - CI/CD orchestration
  - Benchmark automation
  - Reviewer workflows
- `Azure DevOps self-hosted Windows agent`
  - D365 build and validation execution
- Optional `Azure AI Search`
  - Managed hybrid retrieval across documents and code if PostgreSQL search becomes limiting
- `Azure Monitor + Log Analytics`
  - Operational monitoring
  - Build and agent telemetry

### Azure Strengths

- Strong managed-service posture
- Natural fit for Azure DevOps workflows
- Easier integration with other Microsoft tooling
- Simpler scaling for API and worker services

### Azure Trade-offs

- Higher recurring platform cost
- More service sprawl if not carefully controlled
- Azure AI Search should be added only when justified by retrieval needs

## Self-Hosted Architecture

This option is the best fit if you want maximum cost control and infrastructure independence, while keeping the architecture compatible with D365 constraints.

### Recommended Components

- `PostgreSQL`
  - Primary metadata store
  - Graph edge tables
  - Rules and memory tables
  - Optional `pgvector` for embeddings
- `FastAPI` or equivalent application service
  - MCP-style tool APIs
  - Retrieval APIs
  - Indexing APIs
  - Evaluation APIs
- `RabbitMQ`
  - Background job queue
  - Long-running index and build job orchestration
- `MinIO` or filesystem/object storage
  - Source snapshots
  - Exported metadata
  - Build artifacts
  - Logs
- `Docker Compose`
  - Initial deployment model for the knowledge platform services
- Optional `OpenSearch`
  - Add only if PostgreSQL full-text and vector retrieval become insufficient
- Optional `Grafana + Loki`
  - Logging and monitoring
- `Windows VPS or Windows VM`
  - D365 build and validation runner
  - Visual Studio and D365 development tooling
  - Compile, Best Practice checks, cross-reference validation, packaging
- Optional pipeline orchestrator:
  - `Azure DevOps` with self-hosted agents
  - or `GitLab CI`
  - or `Jenkins`

### Self-Hosted Strengths

- Lower platform dependency on Azure
- Better control of cost and infrastructure layout
- Simpler to keep the knowledge stack portable across environments

### Self-Hosted Trade-offs

- More operational responsibility
- More manual work for backup, observability, and scaling
- You still need a Windows build-capable environment for D365 validation

## Architecture Recommendation

For MVP:

- If the company is already Azure-centric, choose the Azure hosting architecture.
- If the goal is maximum flexibility and cost control, choose the self-hosted architecture.

In both cases, the most important invariant is the same:

- One structured metadata store
- One relationship graph or graph-like edge model
- One deterministic build and validation runner
- One retrieval layer that prioritizes exact and graph search before semantic search

## Suggested Infrastructure Profiles

### Small MVP

- One Linux host for metadata, retrieval APIs, and queue
- One Windows host for D365 build and validation

### Medium Deployment

- One Linux host for database
- One Linux host for APIs and background workers
- One Windows host for build and validation

### Larger Deployment

- Dedicated database host
- Dedicated retrieval/API host
- Dedicated ingestion/evaluation worker host
- Dedicated Windows build host

## Proposed Delivery Phases

### Phase 0: Preparation

Deliverables:

- Repository and metadata access
- Build environment access
- Corpus segmentation rules
- Initial sample task set

### Phase 1: Knowledge Foundation

Deliverables:

- Corpus classifier
- Metadata extractor
- Initial normalized schema
- Initial relationship graph

### Phase 2: Retrieval and Tooling

Deliverables:

- Search APIs
- Relationship traversal APIs
- Agent tool endpoints
- Example lookup workflows

### Phase 3: Build Validation Integration

Deliverables:

- Build execution integration
- Best Practice integration
- Error capture and normalization
- Packaging support

### Phase 4: Benchmark and Review System

Deliverables:

- Benchmark suite
- Automated evaluation runs
- Reviewer workflow
- Feedback capture

### Phase 5: Pilot Rollout

Deliverables:

- Controlled usage on real tasks
- Outcome tracking
- Retrieval tuning
- Rule refinement

## 30 / 60 / 90 Day Plan

### First 30 Days

- Segment the corpus
- Extract core metadata
- Build exact search
- Build initial graph
- Define first benchmark set

### First 60 Days

- Add semantic search
- Add agent tools
- Integrate build and Best Practice checks
- Add reverse-reference and extension-chain lookup
- Pilot on a small set of real tasks

### First 90 Days

- Add reviewer lane
- Add benchmark automation
- Expand to reports and security if not already included
- Add memory of accepted and rejected patterns
- Tune retrieval ranking and workflow rules

## Success Criteria

The MVP is successful if it can:

- Correctly identify the main artifact family for common D365 tasks
- Retrieve relevant custom and standard examples reliably
- Produce buildable code for scoped tasks
- Reduce time to solution on benchmark tasks
- Avoid deprecated patterns consistently
- Show measurable improvement over time through feedback

## Main Risks

- Poor source segmentation leads to bad pattern learning
- Missing build access makes output unreliable
- Weak metadata extraction makes retrieval shallow
- Over-reliance on semantic search causes fabricated object references
- Lack of benchmark discipline makes progress hard to measure

## Immediate Next Steps

1. Confirm the MVP scope
2. Provide access to one representative source tree
3. Provide access to one build-capable environment
4. Select the storage/search stack
5. Gather 10 to 20 real historical tasks for benchmarks
6. Start corpus segmentation before any broad AI rollout

## Suggested File Outputs for the Next Stage

The next implementation artifacts should be:

- `architecture.md`
- `metadata-schema.md`
- `tool-catalog.md`
- `benchmark-catalog.md`
- `rollout-plan-30-60-90.md`
