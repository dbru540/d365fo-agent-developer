"""X++/D365 coding-rule linter — the machine-enforced half of the methodology.

`docs/x++-methodology.md` states the development rules in prose (for the agent to read);
`validate.py` checks XML structure. This module closes the gap between them: it turns the
conventions that were *only* prose into **executable checks**, several of which consult the
SQLite knowledge index so they verify against the real corpus rather than guessing.

Design (ESLint-style): rule LOGIC is code (one function per rule, registered below); rule
CONFIG — which rules are on, their severity, shared parameters like the allowed prefixes — is
data in `config/x++-rules.json`. Tune policy without touching code.

Index-backed rules degrade gracefully: when no index is supplied they are skipped and reported
in `rules_skipped` rather than producing false results.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
from xml.etree import ElementTree as ET

DEFAULT_PREFIXES = ["BAB", "Fiveforty", "FLexmind"]

# Built-in fallback config, used when no config file is provided. Mirrors config/x++-rules.json.
DEFAULT_RULE_CONFIG: dict[str, dict[str, object]] = {
    "naming-prefix": {"enabled": True, "severity": "warning", "methodology": "§3"},
    "label-not-literal": {"enabled": True, "severity": "warning", "methodology": "§4"},
    "field-type-matches-edt": {"enabled": True, "severity": "error", "methodology": "§5"},
    "extension-target-exists": {"enabled": True, "severity": "error", "methodology": "§1"},
    "no-legacy-reference": {"enabled": True, "severity": "warning", "methodology": "§9"},
    "privilege-grant-explicit": {"enabled": True, "severity": "info", "methodology": "§6"},
    "data-entity-completeness": {"enabled": True, "severity": "warning", "methodology": "§7"},
}

EXTENSION_FAMILIES = {
    "table-extension",
    "form-extension",
    "class-extension",
    "security-duty-extension",
    "security-role-extension",
}


@dataclass(slots=True)
class LintConfig:
    prefixes: list[str] = field(default_factory=lambda: list(DEFAULT_PREFIXES))
    rules: dict[str, dict[str, object]] = field(default_factory=lambda: dict(DEFAULT_RULE_CONFIG))

    def is_enabled(self, rule_id: str) -> bool:
        return bool(self.rules.get(rule_id, {}).get("enabled", False))

    def severity(self, rule_id: str) -> str:
        return str(self.rules.get(rule_id, {}).get("severity", "warning"))

    def methodology(self, rule_id: str) -> str | None:
        value = self.rules.get(rule_id, {}).get("methodology")
        return str(value) if value else None


def load_lint_config(path: str | Path | None = None) -> LintConfig:
    if path is None:
        return LintConfig()
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return LintConfig(
        prefixes=payload.get("prefixes", DEFAULT_PREFIXES),
        rules=payload.get("rules", DEFAULT_RULE_CONFIG),
    )


@dataclass(slots=True)
class LintContext:
    root: ET.Element
    root_local: str
    family: str | None
    name: str | None
    model: str | None
    index: object | None  # D365Index | None (avoids a hard import cycle)
    prefixes: list[str]
    roots: list | None = None  # file roots to resolve an EDT's XML (read its i:type) when index-backed


# --- XML helpers --------------------------------------------------------------------

def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _iter(root: ET.Element, name: str):
    return (el for el in root.iter() if _local(el.tag) == name)


def _text(root: ET.Element, name: str) -> str | None:
    for el in root.iter():
        if _local(el.tag) == name and el.text:
            return el.text.strip()
    return None


def _attr_local(el: ET.Element, name: str) -> str | None:
    for key, value in el.attrib.items():
        if _local(key) == name:
            return value
    return None


def _extension_target(ctx: LintContext) -> str | None:
    """The object an extension targets: the segment before '.' in the name, or the
    ExtensionOf(...) target parsed from a class declaration."""
    if ctx.name and "." in ctx.name:
        return ctx.name.split(".", 1)[0]
    declaration = _text(ctx.root, "Declaration")
    if declaration:
        import re

        m = re.search(r"ExtensionOf\(\s*\w+\(([A-Za-z0-9_]+)\)", declaration)
        if m:
            return m.group(1)
    return None


# --- EDT base-type resolution (index-backed) ----------------------------------------

_EDT_TYPE_TO_FIELD = {
    "AxEnum": "AxTableFieldEnum",
    "AxEdtEnum": "AxTableFieldEnum",
    "AxEdtInt64": "AxTableFieldInt64",
    "AxEdtInt": "AxTableFieldInt",
    "AxEdtReal": "AxTableFieldReal",
    "AxEdtString": "AxTableFieldString",
    "AxEdtDate": "AxTableFieldDate",
    "AxEdtTime": "AxTableFieldTime",
    "AxEdtUtcDateTime": "AxTableFieldUtcDateTime",
    "AxEdtGuid": "AxTableFieldGuid",
    "AxEdtContainer": "AxTableFieldContainer",
}


def _expected_field_type(edt: str, index: object | None, roots: list | None = None) -> str | None:
    low = edt.lower()
    if low in {"refrecid", "int64"} or low.endswith("recid"):
        return "AxTableFieldInt64"
    if low in {"noyesid"}:
        return "AxTableFieldEnum"
    if index is None:
        return None
    # Complete resolution: read the EDT's real base type from its i:type. This is the ONLY way to
    # type a STANDARD EDT — they are all indexed under the generic 'AxEdt' folder, so the folder-
    # based map below would miss them. Needs file roots; degrade to the folder map when absent.
    if roots:
        try:
            from d365fo_agent.knowledge import resolve_edt_field_type

            resolved = resolve_edt_field_type(index, edt, roots)
        except Exception:
            resolved = None
        if resolved:
            return resolved
    # Folder-based fallback: custom EDTs stored under a subtype-specific folder (AxEdtReal/…).
    try:
        matches = index.lookup_exact(edt)  # type: ignore[attr-defined]
    except Exception:
        matches = []
    for match in matches:
        mapped = _EDT_TYPE_TO_FIELD.get(match.get("artifact_type", ""))
        if mapped:
            return mapped
    return None  # unknown -> do not flag (avoid false positives)


# --- rule checks --------------------------------------------------------------------
# Each returns a list of raw findings {message, element?}; the engine attaches rule_id,
# severity and methodology from config.

def _check_naming_prefix(ctx: LintContext) -> list[dict[str, object]]:
    if not ctx.name:
        return []
    identifier = ctx.name.rsplit(".", 1)[1] if "." in ctx.name else ctx.name
    if any(identifier.startswith(p) for p in ctx.prefixes):
        return []
    kind = "extension model segment" if "." in ctx.name else "object name"
    return [{
        "message": f"{kind} '{identifier}' is not prefixed with one of {ctx.prefixes} — custom artifacts must carry the model/publisher prefix.",
        "element": ctx.name,
    }]


def _check_label_not_literal(ctx: LintContext) -> list[dict[str, object]]:
    findings: list[dict[str, object]] = []
    for tag in ("Label", "HelpText", "DeveloperDocumentation"):
        for el in _iter(ctx.root, tag):
            if el.text and el.text.strip() and not el.text.strip().startswith("@"):
                findings.append({
                    "message": f"<{tag}> uses a literal string '{el.text.strip()[:40]}' instead of a label reference (@File:Id).",
                    "element": tag,
                })
    return findings


def _check_field_type_matches_edt(ctx: LintContext) -> list[dict[str, object]]:
    findings: list[dict[str, object]] = []
    for fieldel in _iter(ctx.root, "AxTableField"):
        itype = _attr_local(fieldel, "type")
        edt = None
        fname = None
        for child in fieldel:
            if _local(child.tag) == "ExtendedDataType" and child.text:
                edt = child.text.strip()
            if _local(child.tag) == "Name" and child.text:
                fname = child.text.strip()
        if not edt:
            continue
        expected = _expected_field_type(edt, ctx.index, ctx.roots)
        if expected and itype and itype != expected:
            findings.append({
                "message": f"Field '{fname}' (EDT '{edt}') is declared as {itype} but its base type implies {expected}. Wrong AOT field type silently corrupts data.",
                "element": fname or edt,
            })
    return findings


def _check_extension_target_exists(ctx: LintContext) -> list[dict[str, object]] | None:
    if ctx.index is None:
        return None  # signal: skip (index required)
    target = _extension_target(ctx)
    if not target:
        return []
    try:
        exists = ctx.index.exists(target)  # type: ignore[attr-defined]
    except Exception:
        return None
    if not exists:
        return [{
            "message": f"Extension target '{target}' was not found in the indexed corpus — it may be misspelled or hallucinated. Verify with element_exists/get_signature.",
            "element": target,
        }]
    return []


def _check_no_legacy_reference(ctx: LintContext) -> list[dict[str, object]] | None:
    if ctx.index is None:
        return None
    target = _extension_target(ctx)
    if not target:
        return []
    try:
        matches = ctx.index.lookup_exact(target)  # type: ignore[attr-defined]
    except Exception:
        return None
    for match in matches:
        if match.get("classification") == "legacy-deprecated":
            return [{
                "message": f"Target '{target}' is classified legacy-deprecated — do not build on it as if it were current best practice.",
                "element": target,
            }]
    return []


def _check_privilege_grant_explicit(ctx: LintContext) -> list[dict[str, object]]:
    if ctx.root_local != "AxSecurityPrivilege":
        return []
    grant_modes: set[str] = set()
    has_entry = False
    for grant in _iter(ctx.root, "Grant"):
        for child in grant:
            has_entry = True
            if child.text and child.text.strip().lower() == "allow":
                grant_modes.add(_local(child.tag))
    if has_entry and grant_modes and grant_modes <= {"Read"}:
        return [{
            "message": "Privilege grants only Read. If the secured operation creates/updates/deletes data, add the matching Create/Update/Delete/Correct grants.",
            "element": ctx.name,
        }]
    return []


def _check_data_entity_completeness(ctx: LintContext) -> list[dict[str, object]]:
    if ctx.root_local != "AxDataEntityView":
        return []
    findings: list[dict[str, object]] = []
    if not _text(ctx.root, "PublicEntityName"):
        findings.append({"message": "Data entity has no <PublicEntityName>.", "element": "PublicEntityName"})
    fields = next(_iter(ctx.root, "Fields"), None)
    if fields is None or len(list(fields)) == 0:
        findings.append({"message": "Data entity has empty <Fields> — a real entity maps fields.", "element": "Fields"})
    keys = next(_iter(ctx.root, "Keys"), None)
    if keys is None or len(list(keys)) == 0:
        findings.append({"message": "Data entity has empty <Keys> — a real entity declares at least a primary key.", "element": "Keys"})
    return findings


_RULES: dict[str, Callable[[LintContext], "list[dict[str, object]] | None"]] = {
    "naming-prefix": _check_naming_prefix,
    "label-not-literal": _check_label_not_literal,
    "field-type-matches-edt": _check_field_type_matches_edt,
    "extension-target-exists": _check_extension_target_exists,
    "no-legacy-reference": _check_no_legacy_reference,
    "privilege-grant-explicit": _check_privilege_grant_explicit,
    "data-entity-completeness": _check_data_entity_completeness,
}


def lint_artifact(
    xml_text: str,
    family: str | None = None,
    *,
    index: object | None = None,
    config: LintConfig | None = None,
    model: str | None = None,
    roots: list | None = None,
) -> dict[str, object]:
    """Run the enabled coding-rule checks against one artifact's XML.

    Returns ``{artifact, family, root, findings, error_count, warning_count, info_count,
    rules_run, rules_skipped}``. ``findings`` carries ``severity`` per item; an ``error``
    means the artifact violates a hard rule.
    """
    config = config or LintConfig()
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        return {
            "artifact": None, "family": family, "root": None,
            "findings": [{"rule_id": "well-formed", "severity": "error", "message": f"XML is not well-formed: {exc}"}],
            "error_count": 1, "warning_count": 0, "info_count": 0, "rules_run": [], "rules_skipped": [],
        }

    name = _text(root, "Name")
    ctx = LintContext(
        root=root, root_local=_local(root.tag), family=family, name=name,
        model=model, index=index, prefixes=config.prefixes, roots=roots,
    )

    findings: list[dict[str, object]] = []
    rules_run: list[str] = []
    rules_skipped: list[dict[str, str]] = []

    for rule_id, check in _RULES.items():
        if not config.is_enabled(rule_id):
            rules_skipped.append({"rule": rule_id, "reason": "disabled"})
            continue
        result = check(ctx)
        if result is None:
            rules_skipped.append({"rule": rule_id, "reason": "requires index (none supplied)"})
            continue
        rules_run.append(rule_id)
        severity = config.severity(rule_id)
        methodology = config.methodology(rule_id)
        for raw in result:
            findings.append({
                "rule_id": rule_id,
                "severity": severity,
                "message": raw["message"],
                "element": raw.get("element"),
                "methodology": methodology,
            })

    return {
        "artifact": name,
        "family": family,
        "root": ctx.root_local,
        "findings": findings,
        "error_count": sum(1 for f in findings if f["severity"] == "error"),
        "warning_count": sum(1 for f in findings if f["severity"] == "warning"),
        "info_count": sum(1 for f in findings if f["severity"] == "info"),
        "rules_run": rules_run,
        "rules_skipped": rules_skipped,
    }
