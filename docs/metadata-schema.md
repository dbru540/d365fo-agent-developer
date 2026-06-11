# Metadata Schema

## Purpose

This schema is the storage target for the local catalog produced by `d365fo_agent.indexer`.

The local toolkit currently keeps data in memory and emits JSON, but the fields are intentionally shaped to map cleanly into PostgreSQL.

## Core Tables

### `artifact`

One row per D365 metadata artifact discovered in the source tree.

| Column | Type | Notes |
| --- | --- | --- |
| `artifact_id` | `uuid` | Primary key |
| `name` | `text` | Artifact name from XML `<Name>` |
| `artifact_type` | `text` | Example: `AxClass`, `AxTableExtension`, `AxReport` |
| `model_name` | `text` | Descriptor/model name |
| `package_name` | `text` | Package folder under the model root |
| `classification` | `text` | `custom-canonical`, `isv-reference`, `legacy-deprecated`, `standard-reference` |
| `relative_path` | `text` | Repo-relative source path |
| `label` | `text null` | Primary label reference if present |
| `is_public` | `boolean` | For entities |
| `data_management_enabled` | `boolean` | For entities |
| `public_entity_name` | `text null` | Entity exposure name |
| `public_collection_name` | `text null` | OData collection name |
| `source_hash` | `text` | Hash for change detection |
| `indexed_at_utc` | `timestamp` | Index timestamp |

Recommended indexes:

- unique `(relative_path)`
- btree `(name)`
- btree `(artifact_type, model_name)`
- btree `(classification)`
- gin/to_tsvector on `name`, `label`, `relative_path`

### `artifact_relation`

Directed edges between artifacts or between an artifact and an external symbolic target.

| Column | Type | Notes |
| --- | --- | --- |
| `relation_id` | `uuid` | Primary key |
| `relation_type` | `text` | Example: `extension-of`, `related-table`, `secured-by`, `xref:MethodCall` |
| `source_name` | `text` | Source artifact or xref source |
| `target_name` | `text` | Target artifact or symbolic target |
| `model_name` | `text` | Owning model |
| `relative_path` | `text` | Source file or xref archive |
| `evidence_kind` | `text` | `xml`, `xref`, `derived` |
| `indexed_at_utc` | `timestamp` | Index timestamp |

Recommended indexes:

- btree `(relation_type, source_name)`
- btree `(relation_type, target_name)`
- btree `(model_name)`

### `model_manifest`

Model-level inventory and curation status.

| Column | Type | Notes |
| --- | --- | --- |
| `model_name` | `text` | Primary key |
| `publisher` | `text null` | From descriptor |
| `description` | `text null` | From descriptor |
| `classification` | `text` | Default model classification |
| `module_references` | `jsonb` | Descriptor references |
| `artifact_count` | `integer` | Indexed artifact count |
| `xref_available` | `boolean` | Whether `.xref` exists |
| `last_indexed_at_utc` | `timestamp` | Last index timestamp |

### `classification_rule`

Persistent retrieval policy.

| Column | Type | Notes |
| --- | --- | --- |
| `rule_id` | `uuid` | Primary key |
| `match_kind` | `text` | `model_exact`, `model_prefix`, `path_contains` |
| `match_value` | `text` | Rule payload |
| `classification` | `text` | Resulting corpus tier |
| `priority` | `integer` | Evaluation order |
| `active` | `boolean` | Soft enable/disable |

### `benchmark_case`

Benchmark definitions used to compare retrieval and coding quality.

| Column | Type | Notes |
| --- | --- | --- |
| `benchmark_id` | `uuid` | Primary key |
| `title` | `text` | Human-readable case |
| `family` | `text` | Example: `security`, `report`, `entity`, `extension` |
| `repo_path` | `text` | Representative file or project path |
| `success_criteria` | `jsonb` | Required observable outcomes |
| `status` | `text` | `candidate`, `approved`, `deprecated` |

### `learning_event`

Persistent memory of outcomes that should affect future ranking or review.

| Column | Type | Notes |
| --- | --- | --- |
| `event_id` | `uuid` | Primary key |
| `event_type` | `text` | `accepted_patch`, `rejected_patch`, `build_failure`, `review_comment` |
| `artifact_name` | `text null` | Related artifact where relevant |
| `summary` | `text` | Short human-readable outcome |
| `payload` | `jsonb` | Raw structured evidence |
| `created_at_utc` | `timestamp` | Event timestamp |

## Relation Vocabulary Implemented Now

The local toolkit already emits these relation types:

- `belongs-to-model`
- `belongs-to-package`
- `uses-label`
- `extension-of`
- `related-table`
- `secured-by`
- `related-to-report`
- `exposed-as-entity`
- `exposed-as-public-collection`
- `xref:MethodCall`
- `xref:TypeReference`

## Mapping from Current Code

- `Artifact` in `src/d365fo_agent/models.py` maps to `artifact`
- `Relation` in `src/d365fo_agent/models.py` maps to `artifact_relation`
- `CorpusRules` in `src/d365fo_agent/rules.py` maps to `classification_rule`

