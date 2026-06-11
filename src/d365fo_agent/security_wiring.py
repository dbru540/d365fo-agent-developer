"""Wire a privilege into the D365 security model — the step that actually grants access.

`entity_derive.build_entity_privilege` produces a privilege, but a privilege on its own grants
nothing: a user only gets access when the privilege is reachable from a role, normally through a
duty. This module emits the duty/role artifacts that close that gap, in the two shapes a senior
D365 developer reaches for:

* **Extension-first (preferred, no overlayering).** Add the privilege to an *existing standard*
  duty via ``AxSecurityDutyExtension`` (every role that already carries that duty then inherits
  it), or attach it to an *existing standard* role via ``AxSecurityRoleExtension``. The extension
  ``Name`` is ``<StandardObject>.<suffix>`` where the suffix carries your model prefix — the
  linter checks the prefix on that suffix segment and verifies ``<StandardObject>`` exists in the
  corpus, so a hallucinated target is caught automatically.
* **New custom duty / role.** When the access is genuinely new (a dedicated integration role),
  emit a fresh ``AxSecurityDuty`` and ``AxSecurityRole``.

Every XML shape here is grounded on real corpus artifacts (BAB-ExportBFC duty extension,
BABCountryRegionVendBankAccount role extension, BABGeneralLedger custom duty/role). The builders
are pure (no index); target-existence verification lives in the MCP/CLI layer that has the index,
mirroring ``entity_derive``.
"""

from __future__ import annotations

_I_NS = "http://www.w3.org/2001/XMLSchema-instance"


def _ref_block(container: str, ref_tag: str, names: list[str]) -> str:
    """Render a reference collection. Empty -> self-closing (matches the corpus), e.g.
    ``\\t<Duties />`` or a populated ``\\t<Privileges>\\n\\t\\t<AxSecurityPrivilegeReference>…``."""
    if not names:
        return f"\t<{container} />"
    inner = "\n".join(
        f"\t\t<{ref_tag}>\n\t\t\t<Name>{name}</Name>\n\t\t</{ref_tag}>" for name in names
    )
    return f"\t<{container}>\n{inner}\n\t</{container}>"


def _default_suffix(privilege_name: str) -> str:
    """Default extension-name suffix. The privilege name is unique and already prefixed, so it is
    a safe default; callers should normally pass their model name instead (e.g. 'BABExportBFC')."""
    return privilege_name


def build_duty_extension(duty_name: str, privileges: list[str], *, suffix: str) -> dict[str, object]:
    """``AxSecurityDutyExtension`` adding ``privileges`` to the standard duty ``duty_name``.
    Name = ``<duty_name>.<suffix>``; the suffix must carry the model prefix."""
    if not privileges:
        raise ValueError("a duty extension must reference at least one privilege")
    name = f"{duty_name}.{suffix}"
    block = _ref_block("Privileges", "AxSecurityPrivilegeReference", privileges)
    xml = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        f'<AxSecurityDutyExtension xmlns:i="{_I_NS}">\n'
        f"\t<Name>{name}</Name>\n"
        f"{block}\n"
        "\t<PropertyModifications />\n"
        "</AxSecurityDutyExtension>\n"
    )
    return {"xml": xml, "name": name, "family": "security-duty-extension",
            "target": duty_name, "privileges": list(privileges)}


def build_role_extension(
    role_name: str, *, suffix: str, duties: list[str] | None = None, privileges: list[str] | None = None,
) -> dict[str, object]:
    """``AxSecurityRoleExtension`` attaching ``duties`` and/or ``privileges`` to the standard role
    ``role_name``. Name = ``<role_name>.<suffix>``."""
    duties = list(duties or [])
    privileges = list(privileges or [])
    if not duties and not privileges:
        raise ValueError("a role extension must reference at least one duty or privilege")
    name = f"{role_name}.{suffix}"
    duties_block = _ref_block("Duties", "AxSecurityDutyReference", duties)
    privs_block = _ref_block("Privileges", "AxSecurityPrivilegeReference", privileges)
    xml = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        f'<AxSecurityRoleExtension xmlns:i="{_I_NS}">\n'
        f"\t<Name>{name}</Name>\n"
        "\t<DirectAccessPermissions />\n"
        f"{duties_block}\n"
        f"{privs_block}\n"
        "\t<PropertyModifications />\n"
        "</AxSecurityRoleExtension>\n"
    )
    return {"xml": xml, "name": name, "family": "security-role-extension",
            "target": role_name, "duties": duties, "privileges": privileges}


def build_duty(name: str, privileges: list[str], *, label: str | None = None) -> dict[str, object]:
    """A new custom ``AxSecurityDuty`` bundling ``privileges``. Children order: Name, Label, Privileges."""
    if not privileges:
        raise ValueError("a duty must reference at least one privilege")
    label_line = f"\t<Label>{label}</Label>\n" if label else ""
    block = _ref_block("Privileges", "AxSecurityPrivilegeReference", privileges)
    xml = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        f'<AxSecurityDuty xmlns:i="{_I_NS}">\n'
        f"\t<Name>{name}</Name>\n"
        f"{label_line}"
        f"{block}\n"
        "</AxSecurityDuty>\n"
    )
    return {"xml": xml, "name": name, "family": "security-duty", "privileges": list(privileges)}


def build_role(
    name: str, *, duties: list[str] | None = None, privileges: list[str] | None = None,
    label: str | None = None, description: str | None = None,
) -> dict[str, object]:
    """A new custom ``AxSecurityRole``. Children order: Name, Description, Label,
    DirectAccessPermissions, Duties, Privileges, SubRoles."""
    duties = list(duties or [])
    privileges = list(privileges or [])
    if not duties and not privileges:
        raise ValueError("a role must reference at least one duty or privilege")
    desc_line = f"\t<Description>{description}</Description>\n" if description else ""
    label_line = f"\t<Label>{label}</Label>\n" if label else ""
    duties_block = _ref_block("Duties", "AxSecurityDutyReference", duties)
    privs_block = _ref_block("Privileges", "AxSecurityPrivilegeReference", privileges)
    xml = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        f'<AxSecurityRole xmlns:i="{_I_NS}">\n'
        f"\t<Name>{name}</Name>\n"
        f"{desc_line}"
        f"{label_line}"
        "\t<DirectAccessPermissions />\n"
        f"{duties_block}\n"
        f"{privs_block}\n"
        "\t<SubRoles />\n"
        "</AxSecurityRole>\n"
    )
    return {"xml": xml, "name": name, "family": "security-role", "duties": duties, "privileges": privileges}


WIRE_REVIEW_CHECKLIST = [
    "Extension targets (the standard duty/role you extend) exist in the corpus — verify with element_exists; the linter's extension-target-exists rule also checks this.",
    "Extension-name suffixes and new duty/role names carry your model prefix (lint: naming-prefix checks the segment after the '.').",
    "Custom duty/role <Label> points to YOUR model's label file (@File:Id), not a literal (lint: label-not-literal).",
    "Extending a standard DUTY propagates the privilege to every role that already carries that duty — confirm that is the intended reach (often you do NOT also need a role extension).",
    "A new custom ROLE grants nothing until assigned to users / a security configuration.",
    "Compile + run the Security Diagnostics / Best-Practice check on a Windows D365 host before shipping.",
]


def wire_security(
    privilege_name: str,
    *,
    duty: str | None = None,
    role: str | None = None,
    extend_duty: bool = True,
    extend_role: bool = True,
    suffix: str | None = None,
    duty_label: str | None = None,
    role_label: str | None = None,
    role_description: str | None = None,
) -> dict[str, object]:
    """Produce the duty/role artifacts that grant ``privilege_name``.

    Provide a ``duty`` (the privilege is placed in it), a ``role`` (it references the duty if one
    was given, otherwise the privilege directly), or both. ``extend_duty`` / ``extend_role`` choose
    between extending an existing *standard* object (``True`` -> ``*Extension``) and creating a new
    *custom* one (``False``). Returns ``{privilege, artifacts:[{family,name,xml,...}], chain,
    review_checklist}``.
    """
    if not duty and not role:
        raise ValueError("wire_security needs at least a duty or a role to wire the privilege into")
    suffix = suffix or _default_suffix(privilege_name)
    artifacts: list[dict[str, object]] = []
    chain: list[str] = [f"privilege:{privilege_name}"]

    if duty:
        if extend_duty:
            art = build_duty_extension(duty, [privilege_name], suffix=suffix)
            chain.append(f"duty-extension:{art['name']}")
        else:
            art = build_duty(duty, [privilege_name], label=duty_label)
            chain.append(f"duty:{art['name']}")
        artifacts.append(art)

    if role:
        role_duties = [duty] if duty else []
        role_privileges = [] if duty else [privilege_name]
        if extend_role:
            art = build_role_extension(role, suffix=suffix, duties=role_duties, privileges=role_privileges)
            chain.append(f"role-extension:{art['name']}")
        else:
            art = build_role(role, duties=role_duties, privileges=role_privileges,
                             label=role_label, description=role_description)
            chain.append(f"role:{art['name']}")
        artifacts.append(art)

    return {
        "privilege": privilege_name,
        "artifacts": artifacts,
        "chain": " -> ".join(chain),
        "review_checklist": WIRE_REVIEW_CHECKLIST,
    }
