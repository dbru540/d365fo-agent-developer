"""Deterministic, offline validation of generated D365 AOT XML.

This is the first rung of the verification ladder: it runs anywhere, with no D365 build
environment, and catches the failures an LLM most often produces — malformed XML, the wrong
root element for the requested family, a missing ``<Name>``, an empty body where structure is
mandatory. Compile + Best-Practice checks (the next rungs) need a Windows D365 host and are
handled by :mod:`d365fo_agent.build`; this module is what makes generation verifiable *today*.
"""

from __future__ import annotations

from xml.etree import ElementTree as ET

# family -> expected AOT root element (mirrors generator.render_artifact)
FAMILY_ROOT = {
    "table": "AxTable",
    "class": "AxClass",
    "form": "AxForm",
    "table-extension": "AxTableExtension",
    "class-extension": "AxClass",
    "data-entity": "AxDataEntityView",
    "form-extension": "AxFormExtension",
    "query": "AxQuery",
    "service": "AxService",
    "service-group": "AxServiceGroup",
    "menu-item-action": "AxMenuItemAction",
    "menu-item-display": "AxMenuItemDisplay",
    "menu-item-output": "AxMenuItemOutput",
    "security-privilege": "AxSecurityPrivilege",
    "security-duty": "AxSecurityDuty",
    "security-role": "AxSecurityRole",
    "security-duty-extension": "AxSecurityDutyExtension",
    "security-role-extension": "AxSecurityRoleExtension",
    "enum": "AxEnum",
    "enum-extension": "AxEnumExtension",
    "edt": "AxEdt",
    "data-entity-view-extension": "AxDataEntityViewExtension",
    "view": "AxView",
}

# Per-root structural expectations. "required" => error if absent; "recommended" => warning.
ROOT_RULES: dict[str, dict[str, list[str]]] = {
    "AxTable": {"required": ["Name", "Fields"], "recommended": ["FieldGroups", "Indexes", "Relations"]},
    "AxForm": {"required": ["Name", "Design"], "recommended": ["DataSources"]},
    "AxTableExtension": {"required": ["Name", "Fields"], "recommended": ["Relations"]},
    "AxClass": {"required": ["Name", "SourceCode"], "recommended": ["Methods"]},
    "AxDataEntityView": {
        "required": ["Name"],
        "recommended": ["PublicEntityName", "PublicCollectionName", "Fields", "Keys"],
    },
    "AxFormExtension": {"required": ["Name", "Controls"], "recommended": []},
    "AxQuery": {"required": ["Name", "DataSources"], "recommended": []},
    "AxService": {"required": ["Name", "Class", "Operations"], "recommended": []},
    "AxServiceGroup": {"required": ["Name", "Services"], "recommended": []},
    "AxMenuItemAction": {"required": ["Name", "Object"], "recommended": ["ObjectType", "Label"]},
    "AxMenuItemDisplay": {"required": ["Name", "Object"], "recommended": ["Label"]},
    "AxMenuItemOutput": {"required": ["Name", "Object"], "recommended": ["ObjectType", "Label"]},
    "AxSecurityPrivilege": {"required": ["Name", "EntryPoints"], "recommended": []},
    "AxSecurityDuty": {"required": ["Name", "Privileges"], "recommended": ["Label"]},
    "AxSecurityRole": {"required": ["Name"], "recommended": ["Duties", "Privileges", "Label"]},
    "AxSecurityDutyExtension": {"required": ["Name", "Privileges"], "recommended": []},
    "AxSecurityRoleExtension": {"required": ["Name"], "recommended": ["Duties", "Privileges"]},
}


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _present_children(root: ET.Element) -> set[str]:
    return {_local(child.tag) for child in root}


def _child_text(root: ET.Element, local_name: str) -> str | None:
    for child in root:
        if _local(child.tag) == local_name and child.text:
            return child.text.strip()
    return None


def validate_xml(
    xml_text: str, family: str | None = None, *, type_profiles: dict[str, dict[str, object]] | None = None
) -> dict[str, object]:
    """Validate one AOT artifact's XML.

    Returns a structured report: ``{valid, root, name, family, rule_source, errors, warnings,
    checks}``. ``errors`` is non-empty iff the artifact would be rejected; ``warnings`` flags likely
    incompleteness that still parses. Pass ``family`` to additionally assert the root element
    matches the requested artifact family.

    Structural rules are resolved in priority order: the hand-curated ``ROOT_RULES`` (authoritative
    for the families it covers), then a corpus-LEARNED profile from ``type_profiles`` (covers the
    long tail — any AOT type), then a generic ``Name``-only fallback. ``rule_source`` reports which
    applied. ``type_profiles`` is the dict produced by :func:`d365fo_agent.type_profile.build_type_profiles`.
    """
    errors: list[str] = []
    warnings: list[str] = []
    checks: list[str] = []

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        return {
            "valid": False,
            "root": None,
            "name": None,
            "family": family,
            "rule_source": None,
            "errors": [f"XML is not well-formed: {exc}"],
            "warnings": [],
            "checks": ["well_formed:fail"],
        }
    checks.append("well_formed:ok")

    root_local = _local(root.tag)
    name = _child_text(root, "Name")

    if family:
        expected = FAMILY_ROOT.get(family)
        if expected is None:
            warnings.append(f"Unknown family '{family}'; skipping root-element check.")
        elif root_local != expected:
            errors.append(f"Root element <{root_local}> does not match family '{family}' (expected <{expected}>).")
        else:
            checks.append(f"root_matches_family:{expected}")

    # Rule resolution: curated (authoritative) -> corpus-learned profile (long tail) -> generic.
    rule_source = "curated"
    rules = ROOT_RULES.get(root_local)
    if rules is None and type_profiles:
        profile = type_profiles.get(root_local)
        if profile:
            rules = {"required": list(profile.get("required", [])), "recommended": list(profile.get("recommended", []))}
            rule_source = "learned"
    if rules is None:
        rules = {"required": ["Name"], "recommended": []}
        rule_source = "generic"
    present = _present_children(root)
    for req in rules.get("required", []):
        if req not in present:
            errors.append(f"Missing required element <{req}> for <{root_local}>.")
        else:
            checks.append(f"has:{req}")
    for rec in rules.get("recommended", []):
        if rec not in present:
            warnings.append(f"Recommended element <{rec}> is absent for <{root_local}> (artifact may be incomplete).")

    if "Name" not in present or not name:
        errors.append("Artifact has no non-empty <Name>.")
    else:
        checks.append(f"name:{name}")

    # Empty-collection heuristic: a container element with no children is suspicious for
    # families where content is the point (services with no operations, etc.).
    for container in ("Fields", "Operations", "EntryPoints", "Controls"):
        for child in root:
            if _local(child.tag) == container and len(list(child)) == 0:
                warnings.append(f"<{container}> is empty — the artifact declares no {container.lower()}.")

    return {
        "valid": len(errors) == 0,
        "root": root_local,
        "name": name,
        "family": family,
        "rule_source": rule_source,
        "errors": errors,
        "warnings": warnings,
        "checks": checks,
    }


def validate_file(
    path: str, family: str | None = None, *, type_profiles: dict[str, dict[str, object]] | None = None
) -> dict[str, object]:
    from pathlib import Path

    text = Path(path).read_text(encoding="utf-8", errors="ignore")
    report = validate_xml(text, family, type_profiles=type_profiles)
    report["path"] = path
    return report
