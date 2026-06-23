# d365fo-agent-developer — D365 F&O X++ knowledge for Claude Code & Codex

A local **MCP server** that gives an AI coding agent (Claude Code, Codex, any MCP host) a grounded
**knowledge base of Dynamics 365 Finance & Operations X++** — so you can develop for D365 quickly
**without re-feeding a whole repo for analysis every time**.

It grounds the agent in real AOT facts: it verifies that a class/table/EDT/enum/entity actually
exists (anti-hallucination), searches the corpus, walks extension/security relationships, serves an
X++ engineering methodology, validates generated XML against learned per-type structure, scaffolds
or deterministically generates artifacts, and (on a Windows D365 host) compiles with the real X++
compiler.

- **Pure Python standard library** — zero runtime dependencies, runs anywhere Python 3.11+ runs.
- **Vendor-neutral** — Claude Code, Codex, Gemini CLI, or any MCP-speaking client over stdio.
- The standard D365 corpus is the same for everyone, so it is indexed **once** and used as a
  portable knowledge base; your own custom code is **optional**.

## Install

```bash
pip install d365fo-agent-developer
# or, isolated:  pipx install d365fo-agent-developer
# or zero-install, straight from PyPI at launch time:  uvx d365fo-agent-developer
```

With `uvx` you can even skip the install entirely — point your MCP client at
`uvx` with args `["d365fo-agent-developer"]` (e.g. in Claude Desktop's
`claude_desktop_config.json`) and the latest published server runs on demand.

This installs two commands: `d365fo-agent-developer` (the MCP server; `d365fo-mcp` is a short alias) and `d365fo-agent` (the CLI).

## Get the knowledge base (once)

Pick one. Both produce a local index at `~/.d365fo-agent/d365fo.db` that the server uses by default.

**A. Download the prebuilt standard-D365 index** (fastest, no D365 install needed):

```bash
d365fo-agent fetch-knowledge          # downloads + caches the standard knowledge index
```

**B. Build it from your own D365 dev box** (no download; uses metadata you already have):

```bash
d365fo-agent build-index \
  --db ~/.d365fo-agent/d365fo.db \
  --packages-root "C:/AOSService/PackagesLocalDirectory" \
  --rebuild
```

> The methodology, default lint rules, and a default learned type-profile ship **inside** the
> package, so validation and guidance work out of the box even before the index is built.

## Wire it into your agent

**Claude Code** — add to `.mcp.json` (project) or `~/.claude.json` (global):

```json
{
  "mcpServers": {
    "d365fo-agent-developer": { "command": "d365fo-agent-developer", "args": [] }
  }
}
```

…or one command: `claude mcp add d365fo-agent-developer d365fo-agent-developer`

**Codex** — add to `~/.codex/config.toml`:

```toml
[mcp_servers.d365fo-agent-developer]
command = "d365fo-agent-developer"
args = []
```

With no `--db`, the server uses the cached knowledge index automatically. That's it — ask the agent
to build something for D365 and it will verify elements, follow the methodology, and validate its
output instead of guessing.

## Add your custom code (optional)

Point the server at your D365 source repo so your **custom** classes/tables/EDTs/enums/extensions
are indexed too, and so the rich tools can read real signatures and clone real examples:

```toml
[mcp_servers.d365fo-agent-developer]
command = "d365fo-agent-developer"
args = ["--repo-root", "C:/path/to/your/D365Repo",
        "--rules", "C:/path/to/your/rules.json",
        "--packages-root", "C:/AOSService/PackagesLocalDirectory"]
```

| Capability | Knowledge index only | + a PackagesLocalDirectory / repo |
|---|---|---|
| Verify an element exists, search, relations, methodology, validation, scaffolding by template | ✅ | ✅ |
| Read a real signature, clone a real example (`get_signature`, `find_similar_examples`, `scaffold_object`) | needs source files | ✅ |
| Compile with the real X++ compiler (`compile_model`) | — | ✅ (Windows D365 host) |

## What the agent gets (MCP tools)

`element_exists`, `find_element`, `search_corpus`, `get_signature`, `get_extension_chain`,
`get_security_links`, `get_entity_exposure`, `find_similar_examples`, `scaffold_object`,
`find_references`, `find_reverse_references`, `analyze_spec`, `generate_from_spec`, `validate_xml`,
`lint_artifact`, `derive_entity`, `wire_security`, `compile_model`, `compile_generated`,
`get_sql_model`, `explore_functional_unit`, `find_relations`, `list_guidance`, `get_guidance`,
`search_guidance`, `get_methodology`, `index_stats`.

The `*_guidance` tools are a queryable X++ **development knowledge base** — the rules, syntax and
logic for coding D365/AX objects (not code to paste). Each topic is platform-tagged
(`d365fo` | `ax2012`), grounded against the corpus (referenced elements are exists-checked), and
illustrated with a real example pulled live from the index.

**Full object-type coverage.** Beyond the rich hand-authored how-to topics (Chain of Command,
table extensions, data entities, security, events, forms, queries/views/menu items, EDT/enum/
labels/number sequences), `get_guidance`/`list_guidance` cover **every AOT object type** (~70):
ask for any type by name (e.g. `AxKPI`, `AxMap`, `AxWorkflowApproval`) and get its corpus-learned
required structure, a real example, and how to scaffold it — derived from the learned type
profiles, so it is grounded by construction with no hand-written-per-type files.

**AX 2012 (multi-platform).** The knowledge base is platform-aware. AX 2012 differs from D365 F&O
(no Chain of Command, overlayering, `.xpo` exports), so it gets its own grounding: index an AX 2012
corpus exported as `.xpo` with `d365fo-agent build-ax-index --db ax2012.db --root <folder>`, then
serve with `--ax-db ax2012.db` (env `D365FO_AX_DB`). `platform: ax2012` guidance topics then ground
and pull examples from that index; `d365fo` topics keep using the D365 F&O knowledge base.

**Functional documentation grounding (Phase 1).** Ground FUNCTIONAL claims (not just AOT metadata)
in cited docs — MS Learn markdown + internal `.docx` — via FTS5 full-text search. Build the index
once, then add `--doc-db` to the server command.

```bash
# Build: index MS Learn clone and/or internal .docx folder
d365fo-agent build-doc-index \
  --db .omx/index/docs.db \
  --mslearn <path-to-mslearn-clone> \
  --mslearn-base-url https://learn.microsoft.com/en-us/dynamics365/finance \
  --internal <path-to-internal-docx-folder> \
  --rebuild
```

```bash
# Serve: add --doc-db (or set D365FO_DOC_DB env var)
d365fo-agent-developer --db .omx/index/d365fo.db --doc-db .omx/index/docs.db
```

Tools enabled: `search_docs` (FTS5 keyword search returning cited chunks), `get_docs` (retrieve a
specific chunk by ID), `docs_stats` (index coverage summary). MS Learn text is indexed locally from
a public [MicrosoftDocs](https://github.com/MicrosoftDocs) clone; nothing is redistributed.

#### Semantic search (optional)

Install the `[semantic]` extra to enable hybrid BM25 → cosine-rerank search:

```bash
pip install d365fo-agent-developer[semantic]
```

This downloads and caches `intfloat/multilingual-e5-small` (ONNX, ~120 MB) on first use.
The model is multilingual (French + English).

**Embed your corpus after indexing:**

```bash
d365fo-agent build-doc-index \
  --db .omx/index/docs.db \
  --internal <docx-folder> \
  [--mslearn <clone>] \
  --embed          # ← computes and stores vectors
```

Or download a prebuilt vector asset (when published):

```bash
d365fo-agent fetch-doc-vectors \
  --db .omx/index/docs.db \
  --url https://github.com/dbru540/d365fo-agent-developer/releases/download/doc-vectors-v1/doc-vectors.db.gz
```

**Without the extra**, the server automatically falls back to FTS5 full-text search — no
configuration change needed.

See [docs/mcp-server.md](docs/mcp-server.md) for the verify-driven workflow and
[docs/x++-methodology.md](docs/x++-methodology.md) for the behavioural contract.

## Maintainer: publish the knowledge index

The wheel stays tiny; the ~100 MB standard index is distributed as a downloadable asset.

```bash
# 1. Build a STANDARD-only index from a PackagesLocalDirectory (no custom repo)
d365fo-agent build-index --db d365fo-standard.db --packages-root <PLD> --rebuild
# 2. (optional) learn type profiles to ship as the default
d365fo-agent build-type-profiles --db d365fo-standard.db --packages-root <PLD> \
  --out src/d365fo_agent/data/aot-type-profiles.json
# 3. Compress and attach to a GitHub release
python -c "import gzip,shutil; shutil.copyfileobj(open('d365fo-standard.db','rb'), gzip.open('d365fo-standard.db.gz','wb'))"
# 4. Point users at it: set DEFAULT_KNOWLEDGE_URL in knowledge_fetch.py (or pass --url)
```

> **Note:** the index holds factual AOT metadata (element names, types, packages, labels,
> relations) — not Microsoft source. Confirm your redistribution position before publishing a
> prebuilt standard index; option **B** above lets each user build their own with zero redistribution.

To publish the package itself: `python -m build` then `python -m twine upload dist/*` (PyPI account
required).

## Develop / contribute

```bash
pip install -e ".[dev]"
PYTHONPATH=src python -m unittest discover -s tests   # full test suite
ruff check src/d365fo_agent tests
```

Docs: [Architecture](docs/architecture.md) · [MCP Server](docs/mcp-server.md) ·
[X++ Methodology](docs/x++-methodology.md) · [Specification Contract](docs/specification-contract.md) ·
[Metadata Schema](docs/metadata-schema.md) · [Tool Catalog](docs/tool-catalog.md)

## License

MIT — see [LICENSE](LICENSE).
