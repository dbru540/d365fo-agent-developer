from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from d365fo_agent.build import BuildRunner
from d365fo_agent.generator import build_generation_bundle, generate_from_spec_file
from d365fo_agent.graph_query import GraphIndex, discover_graph_path
from d365fo_agent.graphify_runner import run_graphify_staging
from d365fo_agent.indexer import (
    build_catalog,
    find_artifacts,
    find_references,
    find_reverse_references,
    get_artifact_details,
    merge_catalogs,
    summarize_classifications,
)
from d365fo_agent.index_store import build_index_file
from d365fo_agent.linter import lint_artifact, load_lint_config
from d365fo_agent.packageslocal_export import export_packageslocal_to_graphify
from d365fo_agent.rules import load_rules
from d365fo_agent.specs import ArtifactSpec, build_artifact_plans, load_spec
from d365fo_agent.validate import FAMILY_ROOT, validate_file, validate_xml


def _force_utf8(*streams: object) -> None:
    """Force UTF-8 on the given text streams. On Windows stdout/stdin default to cp1252,
    which raises UnicodeEncodeError on any character outside that codepage (✓, CJK, …) and
    would corrupt the JSON-RPC stream. MCP mandates UTF-8, so we enforce it everywhere."""
    for stream in streams:
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass


def main(argv: list[str] | None = None) -> int:
    _force_utf8(sys.stdout, sys.stderr, sys.stdin)
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "inventory":
        catalog = _build_catalog_from_args(args)
        payload = {
            "model_count": len(catalog.models),
            "artifact_count": len(catalog.artifacts),
            "classification_summary": summarize_classifications(catalog),
        }
        _dump_json(payload)
        return 0

    if args.command == "find-element":
        catalog = _build_catalog_from_args(args)
        matches = [artifact.to_dict() for artifact in find_artifacts(catalog, args.name, args.artifact_type)]
        _dump_json({"matches": matches})
        return 0

    if args.command == "get-element-details":
        catalog = _build_catalog_from_args(args)
        _dump_json(get_artifact_details(catalog, args.name))
        return 0

    if args.command == "find-references":
        matches = find_references(args.repo_root, args.symbol)
        _dump_json({"matches": matches})
        return 0

    if args.command == "find-reverse-references":
        catalog = _build_catalog_from_args(args)
        _dump_json({"matches": find_reverse_references(catalog, args.symbol)})
        return 0

    if args.command == "build-project":
        runner = BuildRunner(msbuild_executable=args.msbuild)
        result = runner.build_project(
            args.project,
            execute=args.execute,
            output_path=args.output_path,
        )
        _dump_json(asdict(result))
        return 0 if result.status in {"planned", "succeeded"} else 1

    if args.command == "compile-model":
        from d365fo_agent.build import XppCompiler

        compiler = XppCompiler(args.packages_root, xppc_path=args.xppc)
        out = Path(args.output_dir)
        result = compiler.compile_model(
            args.model,
            output_path=out / "out",
            log_path=out / "compile.log",
            appchecker=args.appchecker,
            xref_file=(out / "xref.txt") if args.xref else None,
        )
        _dump_json(result.to_dict())
        if result.status == "succeeded":
            return 0
        return 2 if result.status == "unavailable" else 1

    if args.command == "compile-generated":
        from d365fo_agent.build import XppCompiler

        package = args.package or args.model
        files: list[Path] = []
        if args.generated_dir:
            files += [f for f in Path(args.generated_dir).rglob("*.xml") if not f.name.startswith("generation-")]
        files += [Path(p) for p in (args.file or [])]
        overlays = [
            (f"{package}/{args.model}/{f.parent.name}/{f.name}", f.read_text(encoding="utf-8", errors="ignore"))
            for f in files
        ]
        if not overlays:
            _dump_json({"status": "failed", "message": "No artifact files found (use --generated-dir and/or --file)."})
            return 1
        compiler = XppCompiler(args.packages_root)
        out = Path(args.output_dir)
        result = compiler.compile_overlay(
            args.model, overlays, output_path=out / "out", log_path=out / "compile.log", appchecker=args.appchecker
        )
        _dump_json({**result.to_dict(), "overlaid": [rel for rel, _ in overlays]})
        if result.status == "succeeded":
            return 0
        return 2 if result.status == "unavailable" else 1

    if args.command == "analyze-spec":
        spec = load_spec(args.spec)
        catalog = _build_catalog_from_args(args)
        plans = build_artifact_plans(spec)
        spec_blocks = spec.artifact_specs if spec.artifact_specs else [ArtifactSpec(spec.title, spec.metadata, spec.sections)]
        graph_index = None
        resolved_graph_path = Path(args.graph) if getattr(args, "graph", None) else discover_graph_path(args.repo_root)
        if resolved_graph_path and resolved_graph_path.exists():
            graph_index = GraphIndex(resolved_graph_path)
        bundles = [
            build_generation_bundle(
                spec_block,
                plan,
                catalog,
                args.repo_root,
                example_limit=args.example_limit,
                graph_index=graph_index,
                graph_query=(plan.artifact_name or plan.target_object or plan.service_class),
            )
            for spec_block, plan in zip(spec_blocks, plans, strict=True)
        ]
        payload: dict[str, object] = {"spec": spec.to_dict(), "artifacts": bundles}
        if len(plans) == 1:
            payload["artifact_plan"] = plans[0].to_dict()
            payload["examples"] = bundles[0]["examples"]
        else:
            payload["artifact_plans"] = [plan.to_dict() for plan in plans]
        _dump_json(payload)
        return 0

    if args.command == "generate-from-spec":
        result = generate_from_spec_file(
            args.spec,
            args.repo_root,
            args.rules,
            args.output_dir,
            example_limit=args.example_limit,
            graph_path=getattr(args, "graph", None),
            db_path=getattr(args, "db", None),
        )
        _dump_json(result)
        return 0

    if args.command == "export-packageslocal-graphify":
        result = export_packageslocal_to_graphify(args.packages_root, args.output_dir)
        _dump_json(result)
        return 0

    if args.command == "run-graphify-staging":
        result = run_graphify_staging(args.staging_dir, args.output_dir, include_html=not args.no_html)
        _dump_json(result)
        return 0

    if args.command == "build-index":
        if not args.repo_root and not args.packages_root:
            parser.error("build-index needs --repo-root (custom) and/or --packages-root (standard).")
        # repo_root/rules are optional: omit them to build a STANDARD-only index (the shippable
        # knowledge base) from a PackagesLocalDirectory alone. --repo-root is repeatable: all
        # corpora are merged into ONE catalog because rebuilding "custom" replaces every custom row.
        catalog = None
        if args.repo_root:
            rules = load_rules(args.rules)
            catalog = merge_catalogs([build_catalog(Path(root), rules) for root in args.repo_root])

        def _progress(package: str, count: int) -> None:
            sys.stderr.write(f"[build-index] {package}: +{count}\n")
            sys.stderr.flush()

        stats = build_index_file(
            args.db,
            catalog,
            packages_root=args.packages_root,
            rebuild=args.rebuild,
            progress=_progress if args.packages_root else None,
            exclude_packages=args.exclude_package,
        )
        _dump_json(stats)
        return 0

    if args.command == "extract-aot-relations":
        from d365fo_agent.aot_relations import extract_aot_relations

        def _rel_progress(root: str, count: int) -> None:
            sys.stderr.write(f"[extract-aot-relations] {root}: {count} relations\n")
            sys.stderr.flush()

        stats = extract_aot_relations(args.root, args.db, progress=_rel_progress)
        _dump_json(stats)
        return 0

    if args.command == "serve-mcp":
        from d365fo_agent.mcp_server import build_server_from_config, default_knowledge_db

        db = args.db or (str(default_knowledge_db()) if default_knowledge_db().exists() else None)
        if not db and not args.repo_root:
            parser.error(
                "No knowledge index found. Run 'd365fo-agent fetch-knowledge' to download the standard "
                "D365 knowledge base, or pass --db <index.db> / --repo-root <your D365 repo>."
            )
        server = build_server_from_config(
            args.repo_root,
            args.rules,
            db_path=db,
            packages_root=args.packages_root,
            methodology_path=args.methodology,
            lint_rules_path=args.lint_rules,
            extra_roots=args.extra_root,
            sql_model_path=args.sql_model,
        )
        server.serve_stdio()
        return 0

    if args.command == "fetch-knowledge":
        from d365fo_agent.knowledge_fetch import fetch_knowledge

        result = fetch_knowledge(args.url, args.dest, force=args.force)
        _dump_json(result)
        return 0 if result.get("ok") else 1

    if args.command == "validate-xml":
        profiles = None
        if args.profiles:
            from d365fo_agent.type_profile import load_type_profiles

            profiles = load_type_profiles(args.profiles)
        if args.file:
            report = validate_file(args.file, args.family, type_profiles=profiles)
        else:
            report = validate_xml(sys.stdin.read(), args.family, type_profiles=profiles)
        _dump_json(report)
        return 0 if report["valid"] else 1

    if args.command == "build-type-profiles":
        from d365fo_agent.index_store import D365Index
        from d365fo_agent.type_profile import build_type_profiles, default_profiles_path, save_type_profiles

        roots = [Path(args.repo_root)]
        roots.append(Path(args.packages_root) if args.packages_root else Path(args.repo_root) / "PackagesLocalDirectory")
        index = D365Index(args.db)
        try:
            def _profile_progress(root: str, n: int) -> None:
                sys.stderr.write(f"[type-profiles] {root}: {n}\n")
                sys.stderr.flush()

            profiles = build_type_profiles(index, roots, sample_per_type=args.sample_per_type, progress=_profile_progress)
        finally:
            index.close()
        out = args.out or str(default_profiles_path(args.db))
        save_type_profiles(profiles, out)
        _dump_json({"types_profiled": len(profiles), "output": str(out).replace("\\", "/"),
                    "sample_per_type": args.sample_per_type})
        return 0

    if args.command == "lint":
        from d365fo_agent.index_store import D365Index

        cfg_path = args.rules_config or "config/x++-rules.json"
        config = load_lint_config(cfg_path) if Path(cfg_path).exists() else load_lint_config()
        xml_text = Path(args.file).read_text(encoding="utf-8") if args.file else sys.stdin.read()
        index = D365Index(args.db) if args.db else None
        roots = None
        if args.repo_root:
            roots = [Path(args.repo_root)]
            roots.append(Path(args.packages_root) if args.packages_root else Path(args.repo_root) / "PackagesLocalDirectory")
        try:
            report = lint_artifact(xml_text, args.family, index=index, config=config, model=args.model, roots=roots)
        finally:
            if index is not None:
                index.close()
        _dump_json(report)
        return 0 if report["error_count"] == 0 else 1

    if args.command == "derive-entity":
        from d365fo_agent import entity_derive, knowledge
        from d365fo_agent.index_store import D365Index

        index = D365Index(args.db)
        try:
            matches = index.lookup_exact(args.source, "AxDataEntityView")
            if not matches:
                index.close()
                _dump_json({"found": False, "source": args.source, "error": "source data entity not found in index"})
                return 1
            roots = [Path(args.repo_root), Path(args.repo_root) / "PackagesLocalDirectory"]
            if args.packages_root:
                roots.append(Path(args.packages_root))
            path = knowledge._resolve_file(matches[0].get("relative_path"), roots)
            if path is None:
                _dump_json({"found": True, "source_available": False, "source": args.source})
                return 1
            source_xml = path.read_text(encoding="utf-8", errors="ignore")
            grants = [g.strip() for g in args.grants.split(",")] if args.grants else None
            entity = entity_derive.derive_public_entity(
                source_xml, args.new_name,
                public_entity_name=args.public_entity_name,
                public_collection_name=args.public_collection_name,
                label=args.label,
                data_management=(True if args.data_management else None),
                staging_table=args.staging_table,
            )
            privilege = entity_derive.build_entity_privilege(
                args.new_name, label=args.privilege_label, grants=grants,
                integration_mode=args.integration_mode or "OData",
            )
        finally:
            index.close()

        out_dir = Path(args.output_dir)
        (out_dir / "AxDataEntityView").mkdir(parents=True, exist_ok=True)
        (out_dir / "AxSecurityPrivilege").mkdir(parents=True, exist_ok=True)
        entity_file = out_dir / "AxDataEntityView" / f"{entity['name']}.xml"
        priv_file = out_dir / "AxSecurityPrivilege" / f"{privilege['name']}.xml"
        entity_file.write_text(entity["xml"], encoding="utf-8")
        priv_file.write_text(privilege["xml"], encoding="utf-8")
        _dump_json({
            "source": args.source,
            "entity": {k: v for k, v in entity.items() if k != "xml"},
            "entity_file": str(entity_file).replace("\\", "/"),
            "privilege": {k: v for k, v in privilege.items() if k != "xml"},
            "privilege_file": str(priv_file).replace("\\", "/"),
            "review_checklist": entity_derive.REVIEW_CHECKLIST,
        })
        return 0

    if args.command == "wire-security":
        from d365fo_agent import security_wiring

        extend_duty = not args.new_duty
        extend_role = not args.new_role
        result = security_wiring.wire_security(
            args.privilege, duty=args.duty, role=args.role,
            extend_duty=extend_duty, extend_role=extend_role, suffix=args.suffix,
            duty_label=args.duty_label, role_label=args.role_label, role_description=args.role_description,
        )

        # Verify extension targets against the index (warn, don't block — referenced by name only).
        target_checks: list[dict[str, object]] = []
        warnings: list[str] = []
        if args.db:
            from d365fo_agent.index_store import D365Index

            index = D365Index(args.db)
            try:
                for kind, name, do_extend, atype in (
                    ("duty", args.duty, extend_duty, "AxSecurityDuty"),
                    ("role", args.role, extend_role, "AxSecurityRole"),
                ):
                    if name and do_extend:
                        in_index = index.exists(name, atype)
                        target_checks.append({"kind": kind, "name": name, "in_index": in_index})
                        if not in_index:
                            warnings.append(
                                f"Extension target {kind} '{name}' is not indexed as {atype}. Confirm the exact "
                                f"standard {kind} name, or use --new-{kind} to create a custom object instead."
                            )
            finally:
                index.close()

        out_dir = Path(args.output_dir)
        written = []
        for art in result["artifacts"]:
            folder = FAMILY_ROOT.get(str(art["family"]), "AxUnknown")
            (out_dir / folder).mkdir(parents=True, exist_ok=True)
            fpath = out_dir / folder / f"{art['name']}.xml"
            fpath.write_text(str(art["xml"]), encoding="utf-8")
            written.append({"family": art["family"], "name": art["name"],
                            "file": str(fpath).replace("\\", "/"),
                            "validate": validate_xml(str(art["xml"]), str(art["family"]))})
        _dump_json({
            "wired": True, "privilege": result["privilege"], "chain": result["chain"],
            "artifacts": written, "target_checks": target_checks, "warnings": warnings,
            "review_checklist": result["review_checklist"],
        })
        return 0

    if args.command == "scaffold":
        from d365fo_agent import knowledge
        from d365fo_agent.index_store import D365Index

        properties = {}
        for item in args.set or []:
            if "=" in item:
                key, value = item.split("=", 1)
                properties[key.strip()] = value.strip()
        index = D365Index(args.db)
        try:
            roots = [Path(args.repo_root)]
            roots.append(Path(args.packages_root) if args.packages_root else Path(args.repo_root) / "PackagesLocalDirectory")
            result = knowledge.scaffold_object(
                index, args.artifact_type, roots, new_name=args.new_name, query=args.query,
                properties=properties or None,
            )
        finally:
            index.close()
        if args.output and result.get("xml"):
            out = Path(args.output)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(str(result["xml"]), encoding="utf-8")
            result["written_to"] = str(out).replace("\\", "/")
        _dump_json(result)
        return 0 if result.get("found") else 1

    parser.error(f"Unsupported command: {args.command}")
    return 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="d365fo-agent")
    subparsers = parser.add_subparsers(dest="command", required=True)

    inventory = subparsers.add_parser("inventory")
    _add_catalog_args(inventory)

    find_element = subparsers.add_parser("find-element")
    _add_catalog_args(find_element)
    find_element.add_argument("--name", required=True)
    find_element.add_argument("--artifact-type")

    element_details = subparsers.add_parser("get-element-details")
    _add_catalog_args(element_details)
    element_details.add_argument("--name", required=True)

    references = subparsers.add_parser("find-references")
    references.add_argument("--repo-root", required=True)
    references.add_argument("--symbol", required=True)

    reverse_references = subparsers.add_parser("find-reverse-references")
    _add_catalog_args(reverse_references)
    reverse_references.add_argument("--symbol", required=True)

    build_project = subparsers.add_parser("build-project")
    build_project.add_argument("--project", required=True)
    build_project.add_argument("--output-path")
    build_project.add_argument("--msbuild", default="msbuild.exe")
    build_project.add_argument("--execute", action="store_true")

    compile_model_cmd = subparsers.add_parser(
        "compile-model", help="Compile a model with the real X++ compiler (xppc.exe); structured diagnostics."
    )
    compile_model_cmd.add_argument("--packages-root", required=True, help="PackagesLocalDirectory (metadata + bin/xppc.exe).")
    compile_model_cmd.add_argument("--model", required=True, help="Model/module name to compile (e.g. BABAccountsPayable).")
    compile_model_cmd.add_argument("--output-dir", required=True, help="Where the assembly + compile.log are written.")
    compile_model_cmd.add_argument("--appchecker", action="store_true", help="Also run the Best-Practice (Appchecker) rules.")
    compile_model_cmd.add_argument("--xref", action="store_true", help="Also update the cross-reference data.")
    compile_model_cmd.add_argument("--xppc", help="Override path to xppc.exe (default: <packages-root>/bin/xppc.exe).")

    compile_generated_cmd = subparsers.add_parser(
        "compile-generated",
        help="Overlay generated artifact(s) into their model in the PLD, compile, then restore — proves generated X++ compiles.",
    )
    compile_generated_cmd.add_argument("--packages-root", required=True, help="PackagesLocalDirectory (metadata + bin/xppc.exe).")
    compile_generated_cmd.add_argument("--model", required=True, help="Target model/module the artifacts belong to.")
    compile_generated_cmd.add_argument("--package", help="Package folder (defaults to the model name).")
    compile_generated_cmd.add_argument("--generated-dir", help="A generate-from-spec output dir; all its *.xml are overlaid.")
    compile_generated_cmd.add_argument("--file", action="append", help="An explicit artifact XML file (repeatable).")
    compile_generated_cmd.add_argument("--output-dir", required=True, help="Where the compile log/assembly are written.")
    compile_generated_cmd.add_argument("--appchecker", action="store_true", help="Also run the Best-Practice (Appchecker) rules.")

    analyze_spec = subparsers.add_parser("analyze-spec")
    _add_catalog_args(analyze_spec)
    analyze_spec.add_argument("--spec", required=True)
    analyze_spec.add_argument("--example-limit", type=int, default=3)
    analyze_spec.add_argument("--graph")

    generate_from_spec = subparsers.add_parser("generate-from-spec")
    _add_catalog_args(generate_from_spec)
    generate_from_spec.add_argument("--spec", required=True)
    generate_from_spec.add_argument("--output-dir", required=True)
    generate_from_spec.add_argument("--example-limit", type=int, default=3)
    generate_from_spec.add_argument("--graph")
    generate_from_spec.add_argument("--db", help="SQLite index — resolves table-extension field types from the real EDT base type.")

    export_packageslocal = subparsers.add_parser("export-packageslocal-graphify")
    export_packageslocal.add_argument("--packages-root", required=True)
    export_packageslocal.add_argument("--output-dir", required=True)

    run_graphify = subparsers.add_parser("run-graphify-staging")
    run_graphify.add_argument("--staging-dir", required=True)
    run_graphify.add_argument("--output-dir", required=True)
    run_graphify.add_argument("--no-html", action="store_true")

    build_index = subparsers.add_parser("build-index", help="Build the SQLite FTS5 index (standard and/or custom).")
    build_index.add_argument(
        "--repo-root", action="append", default=None,
        help="Custom D365 source repo (repeatable — all corpora are merged; omit to build a "
             "STANDARD-only knowledge index).",
    )
    build_index.add_argument("--rules", help="Classification rules JSON (required with --repo-root).")
    build_index.add_argument("--db", required=True, help="Output SQLite database path, e.g. .omx/index/d365fo.db")
    build_index.add_argument("--packages-root", help="PackagesLocalDirectory to index the standard D365 corpus.")
    build_index.add_argument("--rebuild", action="store_true", help="Delete and rebuild the DB from scratch.")
    build_index.add_argument(
        "--exclude-package",
        action="append",
        default=None,
        metavar="PATTERN",
        help="fnmatch pattern of PLD packages to skip (repeatable), e.g. --exclude-package 'BAB*' "
             "to keep custom/ISV code out of a publishable standard index.",
    )

    extract_aot = subparsers.add_parser(
        "extract-aot-relations",
        help="Parse <Relations> from every AxTable/AxTableExtension (the AOT foreign keys) "
             "into the SQL data model database.",
    )
    extract_aot.add_argument("--db", required=True, help="SQL model SQLite path, e.g. .omx/index/sqlmodel-raw.db")
    extract_aot.add_argument(
        "--root", action="append", required=True,
        help="Corpus root to walk (repeatable): a PackagesLocalDirectory and/or a source tree.",
    )

    serve_mcp = subparsers.add_parser("serve-mcp", help="Run the stdio MCP server exposing D365 knowledge tools.")
    serve_mcp.add_argument("--repo-root", help="Optional custom D365 repo (omit to serve from the knowledge index alone).")
    serve_mcp.add_argument("--rules", help="Classification rules JSON (only with --repo-root).")
    serve_mcp.add_argument("--db", help="SQLite index path (defaults to the fetched knowledge cache ~/.d365fo-agent/d365fo.db).")
    serve_mcp.add_argument("--packages-root", help="PackagesLocalDirectory — enables source-reading tools (signatures, examples).")
    serve_mcp.add_argument(
        "--extra-root", action="append", default=None,
        help="Additional source corpus root indexed into the same DB (repeatable).",
    )
    serve_mcp.add_argument("--lint-rules", help="X++ lint rules JSON (defaults to the bundled rules).")
    serve_mcp.add_argument(
        "--sql-model",
        help="SQLite SQL data model extracted from a deployed D365 database (enables get_sql_model; "
             "defaults to a sqlmodel-raw.db next to the knowledge index).",
    )
    serve_mcp.add_argument("--methodology")

    fetch_knowledge_cmd = subparsers.add_parser(
        "fetch-knowledge", help="Download the prebuilt standard-D365 knowledge index to the local cache."
    )
    fetch_knowledge_cmd.add_argument("--url", help="Release-asset URL (.db or .db.gz). Defaults to the built-in published URL.")
    fetch_knowledge_cmd.add_argument("--dest", help="Destination path (defaults to ~/.d365fo-agent/d365fo.db).")
    fetch_knowledge_cmd.add_argument("--force", action="store_true", help="Re-download even if already present.")

    validate_xml_cmd = subparsers.add_parser("validate-xml", help="Validate AOT XML (file or stdin) offline.")
    validate_xml_cmd.add_argument("--file", help="Path to the XML file. Omit to read XML from stdin.")
    validate_xml_cmd.add_argument("--family", help="Expected artifact family (e.g. service, data-entity).")
    validate_xml_cmd.add_argument("--profiles", help="Path to aot-type-profiles.json for universal (learned) structural rules.")

    type_profiles_cmd = subparsers.add_parser(
        "build-type-profiles", help="Learn per-type structural rules from the corpus (for universal validate_xml)."
    )
    type_profiles_cmd.add_argument("--repo-root", required=True)
    type_profiles_cmd.add_argument("--db", required=True, help="SQLite index (source of type names + example paths).")
    type_profiles_cmd.add_argument("--packages-root")
    type_profiles_cmd.add_argument("--sample-per-type", type=int, default=200)
    type_profiles_cmd.add_argument("--out", help="Output JSON (default: <db dir>/aot-type-profiles.json).")

    lint_cmd = subparsers.add_parser("lint", help="Lint AOT XML against the X++ coding rules.")
    lint_cmd.add_argument("--file", help="Path to the XML file. Omit to read XML from stdin.")
    lint_cmd.add_argument("--family", help="Artifact family hint (optional).")
    lint_cmd.add_argument("--model", help="Owning model name (optional, refines naming/extension rules).")
    lint_cmd.add_argument("--db", help="SQLite index for index-backed rules (target existence, EDT types).")
    lint_cmd.add_argument("--rules-config", help="Path to x++-rules.json (defaults to config/x++-rules.json).")
    lint_cmd.add_argument("--repo-root", help="Repo root — enables reading EDT i:type to type STANDARD EDT fields.")
    lint_cmd.add_argument("--packages-root", help="PackagesLocalDirectory (defaults to <repo-root>/PackagesLocalDirectory).")

    derive_entity_cmd = subparsers.add_parser(
        "derive-entity", help="Duplicate a standard data entity into a new public OData entity + privilege."
    )
    derive_entity_cmd.add_argument("--repo-root", required=True)
    derive_entity_cmd.add_argument("--db", required=True, help="SQLite index used to locate the source entity.")
    derive_entity_cmd.add_argument("--source", required=True, help="Source data entity name (e.g. CustCustomerV3Entity).")
    derive_entity_cmd.add_argument("--new-name", required=True, help="New custom entity name (prefixed).")
    derive_entity_cmd.add_argument("--output-dir", required=True)
    derive_entity_cmd.add_argument("--packages-root")
    derive_entity_cmd.add_argument("--public-entity-name")
    derive_entity_cmd.add_argument("--public-collection-name")
    derive_entity_cmd.add_argument("--label")
    derive_entity_cmd.add_argument("--data-management", action="store_true")
    derive_entity_cmd.add_argument("--staging-table")
    derive_entity_cmd.add_argument("--integration-mode", default="OData")
    derive_entity_cmd.add_argument("--grants", help="Comma-separated grants, e.g. Read,Create,Update,Delete.")
    derive_entity_cmd.add_argument("--privilege-label")

    wire_security_cmd = subparsers.add_parser(
        "wire-security", help="Wire a privilege into a duty/role (extension-first) so it actually grants access."
    )
    wire_security_cmd.add_argument("--privilege", required=True, help="Privilege name to grant (e.g. from derive-entity).")
    wire_security_cmd.add_argument("--duty", help="Duty to place the privilege in (standard duty to extend, or new custom duty name).")
    wire_security_cmd.add_argument("--role", help="Role to attach the duty/privilege to (standard role to extend, or new custom role name).")
    wire_security_cmd.add_argument("--new-duty", action="store_true", help="Create a new custom AxSecurityDuty instead of extending a standard one.")
    wire_security_cmd.add_argument("--new-role", action="store_true", help="Create a new custom AxSecurityRole instead of extending a standard one.")
    wire_security_cmd.add_argument("--suffix", help="Extension-name suffix (your model name); defaults to the privilege name.")
    wire_security_cmd.add_argument("--duty-label")
    wire_security_cmd.add_argument("--role-label")
    wire_security_cmd.add_argument("--role-description")
    wire_security_cmd.add_argument("--output-dir", required=True)
    wire_security_cmd.add_argument("--db", help="SQLite index to verify standard duty/role targets exist (recommended when extending).")

    scaffold_cmd = subparsers.add_parser(
        "scaffold", help="Clone a real corpus example of ANY AOT type as a starting skeleton for a new object."
    )
    scaffold_cmd.add_argument("--repo-root", required=True)
    scaffold_cmd.add_argument("--db", required=True, help="SQLite index used to find an example.")
    scaffold_cmd.add_argument("--artifact-type", required=True, help="AOT type, e.g. AxView, AxWorkflowApproval, AxEnumExtension.")
    scaffold_cmd.add_argument("--new-name", help="Rename the scaffold's root <Name> to this.")
    scaffold_cmd.add_argument("--query", help="Bias example selection toward a relevant one.")
    scaffold_cmd.add_argument("--set", action="append", metavar="Element=Value",
                              help="Set a top-level element on the skeleton (repeatable), e.g. --set Label=@My:Foo.")
    scaffold_cmd.add_argument("--packages-root")
    scaffold_cmd.add_argument("--output", help="Write the scaffold XML to this path.")

    return parser


def _add_catalog_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--rules", required=True)


def _build_catalog_from_args(args: argparse.Namespace):
    return build_catalog(Path(args.repo_root), load_rules(args.rules))


def _dump_json(payload: dict[str, object]) -> None:
    json.dump(payload, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")


if __name__ == "__main__":
    raise SystemExit(main())
