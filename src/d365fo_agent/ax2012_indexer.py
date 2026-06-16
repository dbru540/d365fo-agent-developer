"""Index a Dynamics AX 2012 corpus exported as ``.xpo`` files (the classic AOT export format).

AX 2012 is a different platform from D365 F&O: no Chain of Command, overlayering instead of
extensions, and the AOT is exported as ``.xpo`` — a line-oriented text format, NOT the per-element
XML of D365's PackagesLocalDirectory. An ``.xpo`` begins with ``Exportfile for AOT version ...``
and contains one or more ``***Element: <CODE>`` blocks, each declaring an exported object with a
``<KEYWORD> #<Name>`` line (``CLASS #Foo``, ``TABLE #Bar``, ``ROLE #Baz`` ...).

This module parses those exports into the same ``Catalog``/``Artifact`` shape the D365 index uses,
so ``D365Index.build_from_catalog(catalog, source="ax2012")`` gives the AX 2012 platform its own
symbol index — ``exists``/``search`` come for free, and platform-tagged guidance grounds against it.

Conservative by design: only the FIRST declaration in each ``***Element`` block (the exported
object) is cataloged — nested references (e.g. standard duties listed inside a custom role) are
NOT, so the index reflects what the corpus actually CONTAINS, not what it merely mentions.
Standard library only.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from d365fo_agent.models import Artifact, Catalog

# .xpo declaration keyword -> AOT type. Keys are ALL-CAPS so they never collide with mixed-case
# property lines (Name/Extends/Label/Origin), which the regex below also excludes.
_KEYWORD_TYPES = {
    "CLASS": "AxClass",
    "INTERFACE": "AxClass",
    "TABLE": "AxTable",
    "MAP": "AxMap",
    "VIEW": "AxView",
    "FORM": "AxForm",
    "REPORT": "AxReport",
    "QUERY": "AxQuery",
    "EXTENDEDDATATYPE": "AxEdt",
    "ENUM": "AxEnum",
    "BASEENUM": "AxEnum",
    "MACRO": "AxMacro",
    "JOB": "AxJob",
    "MENU": "AxMenu",
    "MENUITEMDISPLAY": "AxMenuItemDisplay",
    "MENUITEMOUTPUT": "AxMenuItemOutput",
    "MENUITEMACTION": "AxMenuItemAction",
    "ROLE": "AxSecurityRole",
    "DUTY": "AxSecurityDuty",
    "PRIVILEGE": "AxSecurityPrivilege",
    "PROCESSCYCLE": "AxSecurityProcessCycle",
    "CONFIGURATIONKEY": "AxConfigurationKey",
    "SECURITYKEY": "AxSecurityKey",
    "SERVICE": "AxService",
    "WORKFLOWTEMPLATE": "AxWorkflowTemplate",
    "PERSPECTIVE": "AxPerspective",
}

_ELEMENT_RE = re.compile(r"^\s*\*\*\*Element:")
_DECL_RE = re.compile(r"^\s*([A-Z][A-Z0-9_]+)\s+#(\S+)")
_EXTENDS_RE = re.compile(r"^\s*Extends\s+#(\S+)")


def parse_xpo(path: str | Path) -> list[dict[str, str]]:
    """Parse one ``.xpo`` file into a list of exported elements: {name, artifact_type, extends?}."""
    text = Path(path).read_text(encoding="utf-8", errors="ignore")
    elements: list[dict[str, str]] = []
    # Each ***Element block is one exported object. Split keeping content after each marker.
    blocks = re.split(r"(?m)^\s*\*\*\*Element:.*$", text)
    # blocks[0] is the file header (before the first marker) — skip it.
    for block in blocks[1:]:
        element: dict[str, str] | None = None
        for line in block.splitlines():
            if element is None:
                m = _DECL_RE.match(line)
                if m and m.group(1) in _KEYWORD_TYPES:
                    element = {"name": m.group(2), "artifact_type": _KEYWORD_TYPES[m.group(1)]}
                continue
            ext = _EXTENDS_RE.match(line)
            if ext:
                element["extends"] = ext.group(1)
                break
        if element is not None:
            elements.append(element)
    return elements


def _iter_xpo(root: Path) -> "list[Path]":
    """Collect every ``.xpo`` under ``root``, resilient to unreadable/ghost dirs (OneDrive
    placeholders, deleted entries mid-scan) which would otherwise abort a plain rglob."""
    found: list[Path] = []
    for dirpath, _dirs, filenames in os.walk(root, onerror=lambda _e: None):
        for name in filenames:
            if name.lower().endswith(".xpo"):
                found.append(Path(dirpath) / name)
    return sorted(found)


def build_ax2012_catalog(roots: "list[str | Path]") -> Catalog:
    """Walk every ``.xpo`` under ``roots`` and build a Catalog of AX 2012 custom symbols.

    Deduplicates by (name, artifact_type): an object exported in several projects is one symbol.
    """
    catalog = Catalog()
    seen: set[tuple[str, str]] = set()
    models: set[str] = set()
    for root in roots:
        root = Path(root)
        if not root.exists():
            continue
        files = [root] if root.is_file() else _iter_xpo(root)
        for xpo in files:
            model = xpo.stem
            models.add(model)
            try:
                rel = str(xpo.relative_to(root)).replace("\\", "/") if root.is_dir() else xpo.name
            except ValueError:
                rel = xpo.name
            for element in parse_xpo(xpo):
                key = (element["name"], element["artifact_type"])
                if key in seen:
                    continue
                seen.add(key)
                catalog.artifacts.append(Artifact(
                    name=element["name"],
                    artifact_type=element["artifact_type"],
                    model=model,
                    package="ax2012",
                    classification="ax2012-custom",
                    relative_path=f"{rel}#{element['name']}",
                ))
    catalog.models = sorted(models)
    return catalog
