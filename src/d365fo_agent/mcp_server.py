"""A vendor-neutral MCP server that grounds coding agents in real D365 AOT facts.

This is the autonomy layer. Any MCP-speaking agent (Claude Code, Codex, Gemini CLI, ...)
connects over stdio and gets deterministic tools to verify elements, read signatures, walk
relationships, retrieve idiomatic examples, generate artifacts, and validate output — instead
of guessing X++ from memory.

Design choices:
* **Pure standard library.** JSON-RPC 2.0 over newline-delimited stdio, implemented here. No
  `mcp` pip package, no async framework — so it runs anywhere Python 3.11 runs, with zero install.
* **Prescriptive tool descriptions.** Recent models under-reach for tools by default, so each
  description states *when* to call it ("call this BEFORE referencing any element"). This is the
  difference between an agent that verifies and one that hallucinates.
* **Config via environment / argv**, so the same server binary serves any host.

Run:  ``python -m d365fo_agent.mcp_server --repo-root <repo> --rules <rules.json>``
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import threading
import traceback
from pathlib import Path
from typing import Any, Callable

from d365fo_agent import entity_derive
from d365fo_agent import knowledge as K
from d365fo_agent import linter
from d365fo_agent import security_wiring
from d365fo_agent.build import XppCompiler
from d365fo_agent.index_store import D365Index
from d365fo_agent.validate import validate_xml

PROTOCOL_VERSION = "2025-06-18"
SERVER_NAME = "d365fo-agent-developer"
try:
    from importlib.metadata import version as _dist_version

    SERVER_VERSION = _dist_version("d365fo-agent-developer")
except Exception:  # source tree / not installed
    SERVER_VERSION = "0.0.0-dev"


def _log(message: str) -> None:
    # stdout is the JSON-RPC channel; diagnostics MUST go to stderr.
    print(f"[{SERVER_NAME}] {message}", file=sys.stderr, flush=True)


class D365MCPServer:
    def __init__(
        self,
        repo_root: Path,
        rules_path: Path,
        db_path: Path,
        packages_root: Path | None,
        methodology_path: Path | None,
        lint_config: "linter.LintConfig | None" = None,
        extra_roots: "list[Path] | None" = None,
        sql_model_path: Path | None = None,
        auto_fetch_url: str | None = None,
        ax_db_path: Path | None = None,
        doc_db_path: Path | None = None,
    ) -> None:
        self.sql_model_path = sql_model_path
        self.ax_db_path = ax_db_path
        self.doc_db_path = doc_db_path
        self._doc_index: Any = None
        self.repo_root = repo_root
        self.rules_path = rules_path
        self.db_path = db_path
        self.packages_root = packages_root
        self.methodology_path = methodology_path
        self.lint_config = lint_config or linter.LintConfig()
        # auto_fetch_url: when set and the index file is absent, download it in the background on
        # first serve so the server never crashes on a missing index (no manual fetch-knowledge).
        self.auto_fetch_url = auto_fetch_url
        self._autofetch_started = False
        # extra_roots: additional source corpora indexed into the same DB (their relative_path
        # values resolve from their own root) — e.g. a second client repo.
        self.file_roots = [repo_root, *(extra_roots or [])] + ([packages_root] if packages_root else [])
        self._index: D365Index | None = None
        self._ax_index: D365Index | None = None
        self._catalog: Any = None  # lazily built; reused across calls
        self._type_profiles: dict[str, dict[str, Any]] | None = None
        self._guidance: dict[str, Any] | None = None
        self.tools: dict[str, dict[str, Any]] = {}
        self._register_tools()

    # -- lazy resources ------------------------------------------------------------

    @property
    def guidance(self) -> dict[str, Any]:
        """X++ development knowledge base (rules/syntax/logic topics), loaded once from the bundled
        data/guidance directory. Empty dict if none is shipped (degrades gracefully)."""
        if self._guidance is None:
            from d365fo_agent.guidance import default_guidance_dir, load_guidance

            d = default_guidance_dir()
            self._guidance = load_guidance(d) if d else {}
        return self._guidance

    def _index_if_ready(self) -> "D365Index | None":
        """The index when its file is present, else None — so guidance/example lookups degrade
        instead of raising while an auto-fetch is still in flight."""
        if self.db_path and Path(self.db_path).exists():
            return self.index
        return None

    def _ax_index_if_ready(self) -> "D365Index | None":
        """The AX 2012 index when configured and present, else None."""
        if not self.ax_db_path or not Path(self.ax_db_path).exists():
            return None
        if self._ax_index is None:
            self._ax_index = D365Index(self.ax_db_path)
        return self._ax_index

    def _doc_index_if_ready(self) -> Any:
        """The documentation index when configured and present, else None — so doc tools degrade
        gracefully (like get_sql_model) instead of raising when no docs.db is wired."""
        if not self.doc_db_path or not Path(self.doc_db_path).exists():
            return None
        if self._doc_index is None:
            from d365fo_agent.doc_store import DocIndex

            self._doc_index = DocIndex(self.doc_db_path)
        return self._doc_index

    @property
    def index(self) -> D365Index:
        if self._index is None:
            # Never let sqlite CREATE an empty DB at a not-yet-downloaded cache path: that would
            # poison the auto-fetch (which skips when the file exists) and silently return nothing.
            if not self.db_path or not Path(self.db_path).exists():
                if self.auto_fetch_url:
                    raise RuntimeError(
                        "Knowledge index not ready yet — it is downloading in the background "
                        "(first run can take ~20 s). Retry this call shortly. Methodology, "
                        "validation and scaffolding work meanwhile.")
                raise RuntimeError(
                    "No knowledge index available. Run 'd365fo-agent fetch-knowledge' or pass "
                    "--db <index.db> / --repo-root <your D365 repo>.")
            self._index = D365Index(self.db_path)
        return self._index

    def _maybe_start_autofetch(self) -> None:
        """If configured and the index file is absent, download it once in a daemon thread so the
        stdio handshake is never blocked and the server never crashes on a missing index."""
        if self._autofetch_started or not self.auto_fetch_url:
            return
        if self.db_path and Path(self.db_path).exists():
            return
        self._autofetch_started = True

        def _worker() -> None:
            from d365fo_agent.knowledge_fetch import fetch_knowledge

            _log("knowledge index missing — downloading the standard D365 index in the background "
                 "(first run, ~14 MB)…")
            try:
                result = fetch_knowledge(self.auto_fetch_url, dest=self.db_path)
            except Exception as exc:  # noqa: BLE001 - never let the worker take down the server
                _log(f"auto-fetch error: {exc}")
                return
            if result.get("ok"):
                self._index = None  # force a reopen on the next index access
                _log(f"knowledge index ready: {self.db_path} — index-backed tools are now live.")
            else:
                _log(f"auto-fetch failed: {result.get('error')} (run 'd365fo-agent fetch-knowledge')")

        threading.Thread(target=_worker, name="d365fo-autofetch", daemon=True).start()

    @property
    def type_profiles(self) -> dict[str, dict[str, Any]]:
        """Corpus-learned per-type structural profiles (for universal validate_xml). Loaded once
        from the JSON next to the index DB; an empty dict when none has been built."""
        if self._type_profiles is None:
            from d365fo_agent.type_profile import default_profiles_path, load_type_profiles

            # Prefer a profile built next to this DB (the user's own corpus); fall back to the
            # bundled default so universal validation works out of the box after a plain install.
            profiles = load_type_profiles(default_profiles_path(self.db_path))
            if not profiles:
                data = packaged_data_dir()
                if data is not None:
                    profiles = load_type_profiles(data / "aot-type-profiles.json")
            self._type_profiles = profiles or {}
        return self._type_profiles

    def catalog(self) -> Any:
        if self.rules_path is None:
            raise ValueError(
                "This tool needs the custom-repo catalog. Start the server with --repo-root and "
                "--rules pointing at your D365 source repo to enable it."
            )
        if self._catalog is None:
            from d365fo_agent.indexer import build_catalog
            from d365fo_agent.rules import load_rules

            self._catalog = build_catalog(self.repo_root, load_rules(self.rules_path))
        return self._catalog

    # -- tool registry -------------------------------------------------------------

    def _register_tools(self) -> None:
        def tool(name: str, description: str, schema: dict[str, Any]) -> Callable:
            def register(fn: Callable) -> Callable:
                self.tools[name] = {"description": description, "inputSchema": schema, "handler": fn}
                return fn

            return register

        STR = {"type": "string"}
        INT = {"type": "integer"}
        BOOL = {"type": "boolean"}

        @tool(
            "element_exists",
            "Confirm a D365 AOT element exists BEFORE you reference it in generated X++. "
            "Call this for every class, table, EDT, enum, data entity, or security object you are "
            "about to name. Returns {exists: bool} plus matches. If it returns false, do NOT use "
            "that name — it would be a hallucination.",
            {"type": "object", "properties": {"name": STR, "artifact_type": STR}, "required": ["name"]},
        )
        def element_exists(args: dict[str, Any]) -> dict[str, Any]:
            name = args["name"]
            atype = args.get("artifact_type")
            return {"name": name, "artifact_type": atype, "exists": self.index.exists(name, atype),
                    "matches": self.index.lookup_exact(name, atype, limit=10)}

        @tool(
            "find_element",
            "Find AOT artifacts by exact name (optionally narrowed by type, e.g. AxClass, AxTable). "
            "Use after element_exists when you need the element's model/package/path/classification.",
            {"type": "object", "properties": {"name": STR, "artifact_type": STR, "limit": INT}, "required": ["name"]},
        )
        def find_element(args: dict[str, Any]) -> dict[str, Any]:
            return {"matches": self.index.lookup_exact(args["name"], args.get("artifact_type"), limit=args.get("limit", 25))}

        @tool(
            "search_corpus",
            "Full-text search the indexed D365 corpus (custom code ranks above standard) by names, "
            "labels and paths. Use to discover candidate elements when you don't know the exact name "
            "(e.g. 'vendor invoice posting'). Returns artifacts, not source.",
            {"type": "object", "properties": {"query": STR, "artifact_type": STR, "limit": INT}, "required": ["query"]},
        )
        def search_corpus(args: dict[str, Any]) -> dict[str, Any]:
            return {"results": self.index.search(args["query"], artifact_type=args.get("artifact_type"), limit=args.get("limit", 20))}

        @tool(
            "get_signature",
            "Return the concrete shape of an element: its methods (with real signatures), table "
            "fields (with EDTs), service operations, what it extends, and declaration. Call this "
            "BEFORE calling a method or referencing a field, so you use the real signature instead "
            "of an invented one.",
            {"type": "object", "properties": {"name": STR, "artifact_type": STR}, "required": ["name"]},
        )
        def get_signature(args: dict[str, Any]) -> dict[str, Any]:
            return K.get_signature(self.index, args["name"], self.file_roots, args.get("artifact_type"))

        @tool(
            "get_extension_chain",
            "Walk the extends/extension-of relationships around an element (what it extends, what "
            "extends it, related tables). Use to decide whether your change should be an extension, "
            "a CoC class, or an event handler, and to avoid duplicating an existing extension.",
            {"type": "object", "properties": {"name": STR}, "required": ["name"]},
        )
        def get_extension_chain(args: dict[str, Any]) -> dict[str, Any]:
            return K.get_extension_chain(self.index, args["name"])

        @tool(
            "get_security_links",
            "Show the security wiring around an element: what it secures and what privileges secure "
            "it. Call this before adding a menu item / service operation so you secure it the way "
            "comparable objects are secured.",
            {"type": "object", "properties": {"name": STR}, "required": ["name"]},
        )
        def get_security_links(args: dict[str, Any]) -> dict[str, Any]:
            return K.get_security_links(self.index, args["name"])

        @tool(
            "get_entity_exposure",
            "Report OData / data-management exposure for a data entity or table (IsPublic, "
            "PublicEntityName, PublicCollectionName, DataManagementEnabled). Use before creating or "
            "extending an entity to mirror how a comparable entity is exposed.",
            {"type": "object", "properties": {"name": STR}, "required": ["name"]},
        )
        def get_entity_exposure(args: dict[str, Any]) -> dict[str, Any]:
            return K.get_entity_exposure(self.index, args["name"])

        @tool(
            "find_similar_examples",
            "Retrieve idiomatic in-corpus examples for a task, custom code first. Call this FIRST "
            "when implementing a change, to ground generation in real patterns. Set include_content "
            "to also return the example XML/source.",
            {"type": "object", "properties": {"query": STR, "artifact_type": STR, "limit": INT, "include_content": BOOL},
             "required": ["query"]},
        )
        def find_similar_examples(args: dict[str, Any]) -> dict[str, Any]:
            return K.find_similar_examples(
                self.index, args["query"], self.file_roots,
                artifact_type=args.get("artifact_type"), limit=args.get("limit", 5),
                include_content=bool(args.get("include_content", False)),
            )

        @tool(
            "find_reverse_references",
            "Answer 'what calls or references this symbol?' using the .xref cross-reference data "
            "(safer than text search for call paths). Use to assess the blast radius of a change.",
            {"type": "object", "properties": {"symbol": STR}, "required": ["symbol"]},
        )
        def find_reverse_references(args: dict[str, Any]) -> dict[str, Any]:
            from d365fo_agent.indexer import find_reverse_references as frr

            return {"matches": frr(self.catalog(), args["symbol"])}

        @tool(
            "find_references",
            "Text search for a symbol across the CUSTOM source tree (src/xplusplus/models). Broad "
            "fallback when graph/xref relations are not enough. Scoped to custom code to stay fast.",
            {"type": "object", "properties": {"symbol": STR, "limit": INT}, "required": ["symbol"]},
        )
        def find_references(args: dict[str, Any]) -> dict[str, Any]:
            from d365fo_agent.indexer import find_references as fr

            models_dir = self.repo_root / "src" / "xplusplus" / "models"
            root = models_dir if models_dir.exists() else self.repo_root
            matches = fr(root, args["symbol"])
            limit = args.get("limit", 100)
            return {"count": len(matches), "matches": matches[:limit]}

        @tool(
            "analyze_spec",
            "Parse a structured Markdown/text spec into one or more artifact plans plus grounded "
            "examples, WITHOUT writing files. Use to preview what would be generated and which "
            "examples ground it. See the specification contract in docs/specification-contract.md.",
            {"type": "object", "properties": {"spec_text": STR, "example_limit": INT}, "required": ["spec_text"]},
        )
        def analyze_spec(args: dict[str, Any]) -> dict[str, Any]:
            from d365fo_agent.generator import build_generation_bundle
            from d365fo_agent.specs import ArtifactSpec, build_artifact_plans, parse_spec_text

            spec = parse_spec_text(args["spec_text"])
            plans = build_artifact_plans(spec)
            spec_blocks = spec.artifact_specs or [ArtifactSpec(spec.title, spec.metadata, spec.sections)]
            bundles = [
                build_generation_bundle(block, plan, self.catalog(), self.repo_root, example_limit=args.get("example_limit", 3))
                for block, plan in zip(spec_blocks, plans, strict=True)
            ]
            return {"spec": spec.to_dict(), "artifact_plans": [p.to_dict() for p in plans], "artifacts": bundles}

        @tool(
            "generate_from_spec",
            "Generate candidate D365 artifact XML from a structured spec (merge mode if the target "
            "already exists). Returns the generated file paths AND their content. Always run "
            "validate_xml on the result before presenting it.",
            {"type": "object", "properties": {"spec_text": STR, "output_dir": STR, "example_limit": INT}, "required": ["spec_text"]},
        )
        def generate_from_spec(args: dict[str, Any]) -> dict[str, Any]:
            from d365fo_agent.generator import generate_from_spec_file

            tmp = tempfile.mkdtemp(prefix="d365fo_gen_")
            spec_path = Path(tmp) / "spec.md"
            spec_path.write_text(args["spec_text"], encoding="utf-8")
            out_dir = Path(args["output_dir"]) if args.get("output_dir") else Path(tmp) / "out"
            manifest = generate_from_spec_file(
                spec_path, self.repo_root, self.rules_path, out_dir,
                example_limit=args.get("example_limit", 3), db_path=self.db_path,
            )
            files = {}
            lint = {}
            for rel in manifest.get("generated_files", []):
                fpath = out_dir / rel
                if fpath.exists():
                    content = fpath.read_text(encoding="utf-8", errors="ignore")
                    files[rel] = content
                    # Auto-lint each generated artifact so the caller gets generation + rule
                    # check in one round-trip and can self-correct before presenting it.
                    lint[rel] = linter.lint_artifact(content, index=self.index, config=self.lint_config, roots=self.file_roots)
            return {"manifest": manifest, "output_dir": str(out_dir), "generated": files, "lint": lint}

        @tool(
            "validate_xml",
            "Validate generated AOT XML offline: well-formedness, correct root element for the "
            "artifact family, required/recommended child elements, empty-container warnings. Works "
            "for ANY AOT object type — structural rules come from hand-curated rules for the common "
            "families and from a corpus-LEARNED profile for the rest (the report's 'rule_source' is "
            "curated/learned/generic). ALWAYS call this on any XML you generate before presenting it. "
            "Returns errors and warnings.",
            {"type": "object", "properties": {"xml": STR, "family": STR}, "required": ["xml"]},
        )
        def validate_xml_tool(args: dict[str, Any]) -> dict[str, Any]:
            return validate_xml(args["xml"], args.get("family"), type_profiles=self.type_profiles or None)

        @tool(
            "lint_artifact",
            "Check generated AOT XML against the X++ coding rules (naming prefix, labels-not-"
            "literals, field-type-matches-EDT, extension-target-exists, no-legacy-reference, "
            "privilege grants, data-entity completeness). Index-backed — it verifies targets and "
            "EDT types against the real corpus. Run this together with validate_xml before "
            "presenting any generated artifact; fix every 'error' finding.",
            {"type": "object", "properties": {"xml": STR, "family": STR, "model": STR}, "required": ["xml"]},
        )
        def lint_artifact_tool(args: dict[str, Any]) -> dict[str, Any]:
            return linter.lint_artifact(
                args["xml"], args.get("family"), index=self.index, config=self.lint_config,
                model=args.get("model"), roots=self.file_roots,
            )

        @tool(
            "derive_entity",
            "Expose a standard (or any existing) data entity via OData by DUPLICATING it into a new "
            "public custom entity: clones the real entity XML (all mapped fields/datasources/keys "
            "preserved), sets IsPublic + PublicEntityName/PublicCollectionName, optionally relabels "
            "and enables data management, AND builds the matching security privilege "
            "(DataEntityPermissions). Use this for 'make standard entity X available on the API' — "
            "never edit the standard entity in place. Returns both artifacts, validated + linted, "
            "plus a review checklist. Verify the source name with element_exists first.",
            {
                "type": "object",
                "properties": {
                    "source_entity": STR, "new_name": STR, "public_entity_name": STR,
                    "public_collection_name": STR, "label": STR, "data_management": BOOL,
                    "staging_table": STR, "integration_mode": STR,
                    "grants": {"type": "array", "items": STR}, "privilege_label": STR,
                },
                "required": ["source_entity", "new_name"],
            },
        )
        def derive_entity_tool(args: dict[str, Any]) -> dict[str, Any]:
            source = args["source_entity"]
            matches = self.index.lookup_exact(source, "AxDataEntityView")
            if not matches:
                return {"found": False, "source_entity": source,
                        "error": f"No data entity named '{source}' in the index. Verify with element_exists/search_corpus — do not guess."}
            rel = matches[0].get("relative_path")
            path = K._resolve_file(rel, self.file_roots)
            if path is None:
                return {"found": True, "source_available": False, "source_entity": source, "relative_path": rel,
                        "error": "Source entity is indexed but its XML file could not be located under the configured roots."}
            source_xml = path.read_text(encoding="utf-8", errors="ignore")
            entity = entity_derive.derive_public_entity(
                source_xml, args["new_name"],
                public_entity_name=args.get("public_entity_name"),
                public_collection_name=args.get("public_collection_name"),
                label=args.get("label"),
                data_management=args.get("data_management"),
                staging_table=args.get("staging_table"),
            )
            privilege = entity_derive.build_entity_privilege(
                args["new_name"], label=args.get("privilege_label"),
                grants=args.get("grants"), integration_mode=args.get("integration_mode", "OData"),
            )
            entity_lint = linter.lint_artifact(entity["xml"], "data-entity", index=self.index, config=self.lint_config, roots=self.file_roots)
            priv_lint = linter.lint_artifact(privilege["xml"], "security-privilege", index=self.index, config=self.lint_config, roots=self.file_roots)
            return {
                "found": True, "source_available": True, "source_entity": source,
                "entity": {**{k: v for k, v in entity.items() if k != "xml"}, "xml": entity["xml"],
                           "validate": validate_xml(entity["xml"], "data-entity"), "lint": entity_lint},
                "privilege": {**{k: v for k, v in privilege.items() if k != "xml"}, "xml": privilege["xml"],
                              "validate": validate_xml(privilege["xml"], "security-privilege"), "lint": priv_lint},
                "review_checklist": entity_derive.REVIEW_CHECKLIST,
            }

        @tool(
            "wire_security",
            "Grant a privilege through the security model by generating the duty/role wiring — the "
            "step AFTER derive_entity (a privilege alone grants nothing). Extension-first by default: "
            "adds the privilege to an EXISTING standard duty (AxSecurityDutyExtension) and/or role "
            "(AxSecurityRoleExtension); set extend_duty/extend_role=false to instead CREATE a new "
            "custom duty/role. Provide a duty, a role, or both (the role references the duty if given, "
            "else the privilege directly). When extending, the target is checked against the index by "
            "TYPE and any unverified target is surfaced in 'warnings'/'target_checks' (it does not block "
            "— confirm the name or use extend_*=false). Returns each artifact validated + linted, the "
            "privilege->duty->role chain, and a review checklist. Use suffix=<your model name>.",
            {
                "type": "object",
                "properties": {
                    "privilege": STR, "duty": STR, "role": STR,
                    "extend_duty": BOOL, "extend_role": BOOL, "suffix": STR,
                    "duty_label": STR, "role_label": STR, "role_description": STR,
                },
                "required": ["privilege"],
            },
        )
        def wire_security_tool(args: dict[str, Any]) -> dict[str, Any]:
            duty = args.get("duty")
            role = args.get("role")
            if not duty and not role:
                return {"error": "Provide at least a 'duty' or a 'role' to wire the privilege into."}
            extend_duty = bool(args.get("extend_duty", True))
            extend_role = bool(args.get("extend_role", True))
            result = security_wiring.wire_security(
                args["privilege"], duty=duty, role=role,
                extend_duty=extend_duty, extend_role=extend_role, suffix=args.get("suffix"),
                duty_label=args.get("duty_label"), role_label=args.get("role_label"),
                role_description=args.get("role_description"),
            )
            # Anti-hallucination, typed: when EXTENDING, the target should exist in the corpus as the
            # right kind. We only reference it by name (not its content), so this WARNS rather than
            # blocks — and the typed check is sharper than lint's name-only extension-target rule
            # (a same-named privilege would satisfy lint but not 'is it really a duty/role?').
            target_checks: list[dict[str, Any]] = []
            warnings: list[str] = []
            for kind, name, do_extend, atype in (
                ("duty", duty, extend_duty, "AxSecurityDuty"),
                ("role", role, extend_role, "AxSecurityRole"),
            ):
                if name and do_extend:
                    in_index = self.index.exists(name, atype)
                    target_checks.append({"kind": kind, "name": name, "artifact_type": atype, "in_index": in_index})
                    if not in_index:
                        warnings.append(
                            f"Extension target {kind} '{name}' is not indexed as {atype}. Confirm it is a real "
                            f"standard {kind} (exact name) before shipping, or pass extend_{kind}=false to create a "
                            f"new custom {kind} instead — the extension references it by name regardless."
                        )
            for art in result["artifacts"]:
                art["validate"] = validate_xml(art["xml"], art["family"])
                art["lint"] = linter.lint_artifact(art["xml"], art["family"], index=self.index, config=self.lint_config, roots=self.file_roots)
            return {"wired": True, **result, "target_checks": target_checks, "warnings": warnings}

        @tool(
            "compile_model",
            "Compile a D365 model with the real X++ compiler (xppc.exe) — the top rung of the "
            "verification ladder, beyond validate_xml/lint_artifact. Returns structured compiler "
            "diagnostics (errors/warnings with element + location) parsed from the compile log. Set "
            "appchecker=true to also run the Best-Practice (Appchecker) rules. Requires a Windows "
            "host with PackagesLocalDirectory/bin/xppc.exe; if unavailable it returns "
            "status='unavailable' (not an error) so you know the rung could not run here. Use this "
            "to PROVE generated/changed X++ actually compiles before claiming it is done.",
            {"type": "object", "properties": {"model": STR, "appchecker": BOOL, "xref": BOOL}, "required": ["model"]},
        )
        def compile_model_tool(args: dict[str, Any]) -> dict[str, Any]:
            if not self.packages_root:
                return {"status": "unavailable", "model": args.get("model"),
                        "message": "No packages_root configured — set --packages-root/D365FO_PACKAGES_ROOT to the "
                                   "PackagesLocalDirectory so xppc.exe and the metadata can be found."}
            compiler = XppCompiler(self.packages_root)
            work = Path(tempfile.mkdtemp(prefix="d365fo_compile_"))
            result = compiler.compile_model(
                args["model"],
                output_path=work / "out",
                log_path=work / "compile.log",
                appchecker=bool(args.get("appchecker", False)),
                xref_file=(work / "xref.txt") if args.get("xref") else None,
            )
            return result.to_dict()

        @tool(
            "compile_generated",
            "Compile freshly-GENERATED artifact(s) IN CONTEXT — this closes the generate->compile "
            "loop. It temporarily overlays the artifacts into their model in PackagesLocalDirectory, "
            "runs the REAL X++ compiler, then ALWAYS restores the PLD (added files removed, overwritten "
            "files put back). validate_xml/lint_artifact are offline checks; THIS proves the generated "
            "X++ actually compiles before you claim it is done. Provide model, package (defaults to "
            "model), and the artifacts as [{artifact_type, name, xml}]. Needs a Windows host with "
            "xppc.exe; set appchecker=true to also run Best-Practice rules.",
            {
                "type": "object",
                "properties": {
                    "model": STR, "package": STR, "appchecker": BOOL,
                    "artifacts": {"type": "array", "items": {
                        "type": "object",
                        "properties": {"artifact_type": STR, "name": STR, "xml": STR},
                        "required": ["artifact_type", "name", "xml"],
                    }},
                },
                "required": ["model", "artifacts"],
            },
        )
        def compile_generated_tool(args: dict[str, Any]) -> dict[str, Any]:
            if not self.packages_root:
                return {"status": "unavailable", "model": args.get("model"),
                        "message": "No packages_root configured — set --packages-root/D365FO_PACKAGES_ROOT to the "
                                   "PackagesLocalDirectory so the artifact can be overlaid and compiled."}
            model = args["model"]
            package = args.get("package") or model
            overlays = [
                (f"{package}/{model}/{a['artifact_type']}/{a['name']}.xml", a["xml"])
                for a in args.get("artifacts", [])
                if a.get("xml") and a.get("artifact_type") and a.get("name")
            ]
            if not overlays:
                return {"status": "failed", "model": model,
                        "message": "Provide artifacts as [{artifact_type, name, xml}]."}
            compiler = XppCompiler(self.packages_root)
            work = Path(tempfile.mkdtemp(prefix="d365fo_overlay_"))
            result = compiler.compile_overlay(
                model, overlays, output_path=work / "out", log_path=work / "compile.log",
                appchecker=bool(args.get("appchecker", False)),
            )
            return {**result.to_dict(), "overlaid": [rel for rel, _ in overlays], "model": model, "package": package}

        @tool(
            "scaffold_object",
            "Get a starting skeleton for a NEW AOT object of ANY type by cloning a real corpus "
            "example — this is how to 'help me code a <type>' across the WHOLE AOT (AxView, "
            "AxWorkflowApproval, AxQuery, AxEnumExtension, AxAggregateMeasurement, AxTile, "
            "AxCompositeDataEntityView, …), not just the templated families. Returns the example XML "
            "with the root <Name> renamed to new_name; it is a scaffold to ADAPT, then run "
            "validate_xml + lint_artifact (+ compile_model). Pass artifact_type='Ax<Type>' (see "
            "index_stats for the full list of supported types) and an optional query to pick a "
            "relevant example. Optionally pass 'properties' {Element: value} to set top-level nodes "
            "on the skeleton (e.g. {\"Label\": \"@MyLabels:Foo\", \"ConfigurationKey\": \"LedgerBasic\"}).",
            {"type": "object",
             "properties": {"artifact_type": STR, "new_name": STR, "query": STR,
                            "properties": {"type": "object", "additionalProperties": STR}},
             "required": ["artifact_type"]},
        )
        def scaffold_object_tool(args: dict[str, Any]) -> dict[str, Any]:
            return K.scaffold_object(
                self.index, args["artifact_type"], self.file_roots,
                new_name=args.get("new_name"), query=args.get("query"), properties=args.get("properties"),
            )

        @tool(
            "get_methodology",
            "Return the X++/D365 engineering methodology (extension-first, CoC vs events, naming, "
            "labels, security, entities, anti-patterns). Read this once at the start of a D365 task "
            "to align with the required development practices.",
            {"type": "object", "properties": {}},
        )
        def get_methodology(args: dict[str, Any]) -> dict[str, Any]:
            if self.methodology_path and self.methodology_path.exists():
                return {"methodology": self.methodology_path.read_text(encoding="utf-8")}
            return {"methodology": None, "error": "methodology file not configured/found"}

        @tool(
            "index_stats",
            "Report the index coverage: total/custom/standard artifact counts, relations, packages, "
            "and a breakdown by artifact type. Use to understand what the corpus does and does not cover.",
            {"type": "object", "properties": {}},
        )
        def index_stats(args: dict[str, Any]) -> dict[str, Any]:
            from d365fo_agent.sql_model import sql_model_stats

            return {"stats": self.index.stats(),
                    "supported_object_types": self.index.list_types(),
                    "by_type_custom": self.index.counts_by_type(source="custom", limit=60),
                    "by_type_standard": self.index.counts_by_type(source="standard", limit=80),
                    "sql_model": sql_model_stats(self.sql_model_path) if self.sql_model_path
                                 else {"available": False}}

        @tool(
            "list_guidance",
            "List the available X++ development guidance topics (rules, syntax and logic for coding "
            "D365/AX objects — NOT code snippets). Filter by platform (d365fo | ax2012) or AOT "
            "object type. Call this to discover what coding guidance exists before get_guidance.",
            {"type": "object", "properties": {
                "platform": {"type": "string", "description": "d365fo | ax2012 | both"},
                "object_type": {"type": "string", "description": "AOT type, e.g. AxClass, AxTableExtension"},
            }},
        )
        def list_guidance(args: dict[str, Any]) -> dict[str, Any]:
            from d365fo_agent.guidance import list_guidance as _list

            return {"topics": _list(self.guidance, platform=args.get("platform"),
                                    object_type=args.get("object_type"),
                                    type_profiles=self.type_profiles)}

        @tool(
            "get_guidance",
            "Return the X++ coding knowledge for a topic: the SYNTAX (language constructs), the "
            "RULES (what is valid where, constraints) and the LOGIC (when/why, pitfalls) needed to "
            "WRITE correct code — plus each referenced element annotated with whether it exists in "
            "the corpus (anti-hallucination) and a REAL example pulled from the index. Call this "
            "BEFORE writing X++ for a task so you code from the rules, not from a guess. Works for "
            "the rich how-to topics AND for ANY AOT object type by name (e.g. AxKPI, AxMap, "
            "AxWorkflowApproval) — it then returns that type's corpus-learned required structure "
            "plus a real example and how to scaffold it.",
            {"type": "object", "properties": {
                "topic": {"type": "string", "description": "Topic id, e.g. coc-extension (see list_guidance)"},
            }, "required": ["topic"]},
        )
        def get_guidance(args: dict[str, Any]) -> dict[str, Any]:
            from d365fo_agent.guidance import get_guidance as _get

            return _get(self.guidance, args["topic"], index=self._index_if_ready(),
                        ax_index=self._ax_index_if_ready(), roots=self.file_roots,
                        type_profiles=self.type_profiles)

        @tool(
            "search_guidance",
            "Find the X++ coding guidance topic(s) that match a task phrased in natural language "
            "(e.g. 'how do I add a field to a standard table', 'extend a method', 'expose an "
            "entity over OData'). Returns ranked topics; follow with get_guidance.",
            {"type": "object", "properties": {
                "query": {"type": "string", "description": "Task in natural language"},
                "platform": {"type": "string", "description": "d365fo | ax2012 | both"},
            }, "required": ["query"]},
        )
        def search_guidance(args: dict[str, Any]) -> dict[str, Any]:
            from d365fo_agent.guidance import search_guidance as _search

            return {"results": _search(self.guidance, args["query"], platform=args.get("platform"),
                                       type_profiles=self.type_profiles)}

        @tool(
            "get_sql_model",
            "Return the REAL SQL shape of a data entity or table as deployed in a D365 database: "
            "typed SQL columns, the base tables it reads (each with its functional unit — invoice, "
            "settlement, financial dimensions, ...), its own functional unit, and optionally the "
            "full T-SQL view definition (the actual joins). Call this when working on OData, Data "
            "management, BYOD, reporting or integrations, so column lists and joins come from the "
            "physical model instead of guesses.",
            {"type": "object", "properties": {
                "name": {"type": "string", "description": "Entity/view or table name (case-insensitive), e.g. CustCustomerV3Entity or CUSTTABLE"},
                "include_definition": {"type": "boolean", "description": "Include the T-SQL view definition (truncated at 20k chars)"},
            }, "required": ["name"]},
        )
        def get_sql_model(args: dict[str, Any]) -> dict[str, Any]:
            from d365fo_agent.sql_model import get_sql_model as lookup

            if not self.sql_model_path:
                return {"found": False, "error": "No SQL model configured. Extract one from a D365 "
                        "database and pass it with --sql-model (or D365FO_SQL_MODEL)."}
            return lookup(self.sql_model_path, args["name"],
                          include_definition=bool(args.get("include_definition")))

        @tool(
            "explore_functional_unit",
            "Describe a business domain (functional unit) of the D365 data model: its core tables "
            "(most referenced by entity views), its main entities, and its interfaces to other "
            "domains (with example bridge entities). Call this to answer functional questions like "
            "'how does settlement work and what does it connect to' or to pick the right entities "
            "for a reporting/integration scope. Units include: facture-client, facture-fournisseur, "
            "lettrage-reglement, dimension-financiere, comptabilite-generale, paiement, banque, "
            "taxe, client, fournisseur, tiers-partie, achat, vente, stock-inventaire, ...",
            {"type": "object", "properties": {
                "unit": {"type": "string", "description": "Functional unit name, e.g. lettrage-reglement"},
                "top": {"type": "integer", "description": "Max items per list (default 15)"},
            }, "required": ["unit"]},
        )
        def explore_functional_unit(args: dict[str, Any]) -> dict[str, Any]:
            from d365fo_agent.sql_model import explore_functional_unit as explore

            if not self.sql_model_path:
                return {"found": False, "error": "No SQL model configured (--sql-model / D365FO_SQL_MODEL)."}
            return explore(self.sql_model_path, args["unit"], top=int(args.get("top", 15)))

        @tool(
            "find_relations",
            "Explain how two objects of the D365 data model relate. Two TABLES: the entity views "
            "that join them (the SQL proof of the relationship — AX databases have no foreign "
            "keys). Two ENTITIES/views: their shared base tables. A view and a table: whether the "
            "view reads the table (directly or through nested views). When the two objects belong "
            "to different functional units, also returns the inter-domain interface (bridge-view "
            "count + examples). Call this BEFORE asserting any relationship between tables or "
            "entities.",
            {"type": "object", "properties": {
                "a": {"type": "string", "description": "First table/entity name, e.g. CUSTTABLE"},
                "b": {"type": "string", "description": "Second table/entity name, e.g. VENDTABLE"},
            }, "required": ["a", "b"]},
        )
        def find_relations(args: dict[str, Any]) -> dict[str, Any]:
            from d365fo_agent.sql_model import find_relations as relate

            if not self.sql_model_path:
                return {"found": False, "error": "No SQL model configured (--sql-model / D365FO_SQL_MODEL)."}
            return relate(self.sql_model_path, args["a"], args["b"])

        _NO_DOCS = ("No documentation index configured. Build one with 'd365fo-agent build-doc-index' "
                    "and start the server with --doc-db / D365FO_DOC_DB.")

        @tool(
            "search_docs",
            "Search the INGESTED D365 functional documentation (MS Learn + internal specs) for "
            "prose that grounds a FUNCTIONAL question — e.g. 'how does vendor invoice matching work'. "
            "Use this to ground functional behaviour BEFORE writing it from memory; every hit carries "
            "its source citation (source_ref). Complements the AOT/symbol tools (which ground "
            "technical facts). Returns ranked chunks with a snippet, not full pages.",
            {"type": "object", "properties": {
                "query": STR, "platform": STR, "module": STR, "origin": STR, "limit": INT,
            }, "required": ["query"]},
        )
        def search_docs(args: dict[str, Any]) -> dict[str, Any]:
            di = self._doc_index_if_ready()
            if di is None:
                return {"found": False, "error": _NO_DOCS}
            return {"found": True, "results": di.search(
                args["query"], platform=args.get("platform"), module=args.get("module"),
                origin=args.get("origin"), limit=int(args.get("limit", 10)))}

        @tool(
            "get_docs",
            "Return one full documentation chunk by its id (from search_docs results), with its "
            "title, source citation and full text. Use to read the passage you intend to cite.",
            {"type": "object", "properties": {"chunk_id": INT}, "required": ["chunk_id"]},
        )
        def get_docs(args: dict[str, Any]) -> dict[str, Any]:
            di = self._doc_index_if_ready()
            if di is None:
                return {"found": False, "error": _NO_DOCS}
            chunk = di.get(int(args["chunk_id"]))
            return chunk if chunk else {"found": False, "error": f"No documentation chunk {args['chunk_id']}."}

        @tool(
            "docs_stats",
            "Report documentation-index coverage: chunk counts by origin (mslearn/internal) and "
            "whether semantic vectors are present. Use to see what functional docs are grounded.",
            {"type": "object", "properties": {}},
        )
        def docs_stats(args: dict[str, Any]) -> dict[str, Any]:
            di = self._doc_index_if_ready()
            if di is None:
                return {"found": False, "error": _NO_DOCS}
            return di.stats()

    # -- resources -----------------------------------------------------------------

    def list_resources(self) -> list[dict[str, Any]]:
        resources = []
        if self.methodology_path and self.methodology_path.exists():
            resources.append({
                "uri": "d365fo://methodology",
                "name": "X++ / D365 Engineering Methodology",
                "description": "Binding development practices for generating D365 code.",
                "mimeType": "text/markdown",
            })
        return resources

    def read_resource(self, uri: str) -> dict[str, Any]:
        if uri == "d365fo://methodology" and self.methodology_path and self.methodology_path.exists():
            return {"contents": [{"uri": uri, "mimeType": "text/markdown",
                                  "text": self.methodology_path.read_text(encoding="utf-8")}]}
        raise ValueError(f"Unknown resource: {uri}")

    # -- JSON-RPC dispatch ---------------------------------------------------------

    def handle(self, message: dict[str, Any]) -> dict[str, Any] | None:
        method = message.get("method")
        msg_id = message.get("id")
        params = message.get("params") or {}

        # Notifications (no id) get no response.
        if method == "notifications/initialized" or (method and method.startswith("notifications/")):
            return None

        try:
            result = self._dispatch(method, params)
        except _RpcError as exc:
            return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": exc.code, "message": exc.message}}
        except Exception as exc:  # noqa: BLE001 - report any handler failure as JSON-RPC error
            _log("handler error: " + "".join(traceback.format_exception(exc)))
            return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32603, "message": f"Internal error: {exc}"}}

        if msg_id is None:
            return None
        return {"jsonrpc": "2.0", "id": msg_id, "result": result}

    def _dispatch(self, method: str | None, params: dict[str, Any]) -> dict[str, Any]:
        if method == "initialize":
            return {
                "protocolVersion": params.get("protocolVersion", PROTOCOL_VERSION),
                "capabilities": {"tools": {}, "resources": {}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            }
        if method == "ping":
            return {}
        if method == "tools/list":
            return {"tools": [{"name": n, "description": t["description"], "inputSchema": t["inputSchema"]}
                              for n, t in self.tools.items()]}
        if method == "tools/call":
            return self._call_tool(params)
        if method == "resources/list":
            return {"resources": self.list_resources()}
        if method == "resources/read":
            return self.read_resource(params.get("uri", ""))
        raise _RpcError(-32601, f"Method not found: {method}")

    def _call_tool(self, params: dict[str, Any]) -> dict[str, Any]:
        name = params.get("name")
        arguments = params.get("arguments") or {}
        tool = self.tools.get(name)
        if tool is None:
            raise _RpcError(-32602, f"Unknown tool: {name}")
        try:
            result = tool["handler"](arguments)
            text = json.dumps(result, indent=2, ensure_ascii=False)
            return {"content": [{"type": "text", "text": text}], "isError": False}
        except _RpcError:
            raise
        except Exception as exc:  # noqa: BLE001 - surface tool failure as a tool error, not a crash
            _log(f"tool '{name}' failed: " + "".join(traceback.format_exception(exc)))
            return {"content": [{"type": "text", "text": f"Tool '{name}' failed: {exc}"}], "isError": True}

    # -- stdio loop ----------------------------------------------------------------

    def serve_stdio(self, stdin: Any = None, stdout: Any = None) -> None:
        stdin = stdin or sys.stdin
        stdout = stdout or sys.stdout
        # MCP mandates UTF-8 on the wire. On Windows the std streams default to cp1252, which
        # raises UnicodeEncodeError on any non-cp1252 char (✓, CJK, some symbols) and corrupts
        # the JSON-RPC stream. Force UTF-8; guarded so StringIO test doubles are left untouched.
        for stream in (stdin, stdout, sys.stderr):
            try:
                stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
            except (AttributeError, ValueError):
                pass
        _log(f"serving {len(self.tools)} tools; repo={self.repo_root} db={self.db_path}")
        self._maybe_start_autofetch()
        for line in stdin:
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                _log(f"skipping non-JSON line: {line[:120]}")
                continue
            response = self.handle(message)
            if response is not None:
                stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
                stdout.flush()


class _RpcError(Exception):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def packaged_data_dir() -> Path | None:
    """The bundled ``d365fo_agent/data`` directory (methodology, default lint rules, default type
    profiles), so the server works after a plain ``pip install`` — not just from the source tree."""
    try:
        from importlib.resources import files

        data = Path(str(files("d365fo_agent").joinpath("data")))
        return data if data.exists() else None
    except Exception:  # noqa: BLE001 - any resolution failure -> no packaged data
        return None


def _first_existing(*candidates: "Path | None") -> Path | None:
    for candidate in candidates:
        if candidate is not None and candidate.exists():
            return candidate
    return None


def default_knowledge_db() -> Path:
    """Local cache for the downloaded standard-D365 knowledge index (``fetch-knowledge``)."""
    return Path.home() / ".d365fo-agent" / "d365fo.db"


def build_server_from_config(
    repo_root: str | Path | None = None,
    rules_path: str | Path | None = None,
    *,
    db_path: str | Path | None = None,
    packages_root: str | Path | None = None,
    methodology_path: str | Path | None = None,
    lint_rules_path: str | Path | None = None,
    extra_roots: "list[str | Path] | None" = None,
    sql_model_path: str | Path | None = None,
    auto_fetch_url: str | None = None,
    ax_db_path: str | Path | None = None,
    doc_db_path: str | Path | None = None,
) -> D365MCPServer:
    # repo_root/rules are OPTIONAL: in "embedded knowledge base" mode the server runs from a
    # prebuilt index alone (no custom repo). They are only needed for catalog-backed tools.
    repo_root = Path(repo_root).resolve() if repo_root else Path.cwd()
    rules_path = Path(rules_path).resolve() if rules_path else None
    db_path = Path(db_path).resolve() if db_path else (repo_root / ".." / ".omx" / "index" / "d365fo.db").resolve()
    pkg = Path(packages_root) if packages_root else (repo_root / "PackagesLocalDirectory")
    pkg = pkg if pkg.exists() else None
    # Resolve methodology + lint rules: explicit flag > source tree (dev) > bundled package data
    # (installed). The bundled copies are what make the server work after `pip install`.
    project_root = Path(__file__).resolve().parents[2]
    data = packaged_data_dir()
    method = (
        Path(methodology_path) if methodology_path
        else _first_existing(project_root / "docs" / "x++-methodology.md",
                              (data / "x++-methodology.md") if data else None)
    )
    lint_path = (
        Path(lint_rules_path) if lint_rules_path
        else _first_existing(project_root / "config" / "x++-rules.json",
                             (data / "x++-rules.json") if data else None)
    )
    lint_config = linter.load_lint_config(lint_path) if lint_path else linter.LintConfig()
    roots = [Path(r).resolve() for r in (extra_roots or [])]
    # SQL model: explicit flag/env, else a sqlmodel-raw.db sitting next to the knowledge index.
    sql_model = Path(sql_model_path).resolve() if sql_model_path else None
    if sql_model is None:
        sibling = db_path.parent / "sqlmodel-raw.db"
        sql_model = sibling if sibling.exists() else None
    ax_db = Path(ax_db_path).resolve() if ax_db_path else None
    doc_db = Path(doc_db_path).resolve() if doc_db_path else None
    if doc_db is None:
        sibling = db_path.parent / "docs.db"
        doc_db = sibling if sibling.exists() else None
    return D365MCPServer(repo_root, rules_path, db_path, pkg, method, lint_config=lint_config,
                         extra_roots=roots, sql_model_path=sql_model, auto_fetch_url=auto_fetch_url,
                         ax_db_path=ax_db, doc_db_path=doc_db)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="d365fo-agent-developer",
                                     description="D365 F&O knowledge MCP server (stdio).")
    parser.add_argument("--repo-root", default=os.environ.get("D365FO_REPO_ROOT"))
    parser.add_argument("--rules", default=os.environ.get("D365FO_RULES"))
    parser.add_argument("--db", default=os.environ.get("D365FO_DB"))
    parser.add_argument("--packages-root", default=os.environ.get("D365FO_PACKAGES_ROOT"))
    parser.add_argument("--methodology", default=os.environ.get("D365FO_METHODOLOGY"))
    parser.add_argument("--lint-rules", default=os.environ.get("D365FO_LINT_RULES"))
    parser.add_argument(
        "--extra-root", action="append",
        default=(os.environ.get("D365FO_EXTRA_ROOTS", "").split(os.pathsep)
                 if os.environ.get("D365FO_EXTRA_ROOTS") else None),
        help="Additional source corpus root indexed into the same DB (repeatable; "
             "env D365FO_EXTRA_ROOTS, path-separator separated).",
    )
    parser.add_argument(
        "--sql-model", default=os.environ.get("D365FO_SQL_MODEL"),
        help="SQLite SQL data model extracted from a deployed D365 database (enables get_sql_model; "
             "defaults to a sqlmodel-raw.db next to the knowledge index).",
    )
    parser.add_argument(
        "--ax-db", default=os.environ.get("D365FO_AX_DB"),
        help="AX 2012 index (from build-ax-index) — grounds platform:ax2012 guidance topics.",
    )
    parser.add_argument(
        "--doc-db", default=os.environ.get("D365FO_DOC_DB"),
        help="Documentation index (from build-doc-index) — enables search_docs/get_docs/docs_stats.",
    )
    args = parser.parse_args(argv)

    # Embedded-knowledge mode: run from a prebuilt index alone (no repo). Default the DB to the
    # downloaded knowledge cache.
    db = args.db or (str(default_knowledge_db()) if default_knowledge_db().exists() else None)
    auto_fetch_url = None
    if not db and not args.repo_root:
        # No index, no repo: instead of crashing, start in degraded mode (methodology, validation
        # and scaffolding still work from bundled data) and auto-download the standard index in the
        # background on first run. Opt out with D365FO_NO_AUTOFETCH=1 (offline/CI).
        from d365fo_agent.knowledge_fetch import DEFAULT_KNOWLEDGE_URL

        if DEFAULT_KNOWLEDGE_URL and not os.environ.get("D365FO_NO_AUTOFETCH"):
            db = str(default_knowledge_db())  # target cache path; the file does not exist yet
            auto_fetch_url = DEFAULT_KNOWLEDGE_URL
        else:
            parser.error(
                "No knowledge index found. Run 'd365fo-agent fetch-knowledge' to download the "
                "standard D365 knowledge base, or pass --db <index.db> / --repo-root <your repo>."
            )

    server = build_server_from_config(
        args.repo_root, args.rules, db_path=db, packages_root=args.packages_root,
        methodology_path=args.methodology, lint_rules_path=args.lint_rules,
        extra_roots=args.extra_root, sql_model_path=args.sql_model, auto_fetch_url=auto_fetch_url,
        ax_db_path=args.ax_db, doc_db_path=args.doc_db,
    )
    server.serve_stdio()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
