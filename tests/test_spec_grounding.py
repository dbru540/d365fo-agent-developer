# tests/test_spec_grounding.py
"""Unit tests for spec_grounding — tag parsing, registry, unverified detection, FDD validation.

All inputs are synthetic Markdown strings; no file I/O needed. Standard library only.
"""

from d365fo_agent.spec_grounding import (
    Claim,
    build_grounding_registry,
    find_unverified_claims,
    parse_grounding_tags,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

VERIFIED_MD = (
    "Le module AP gère les factures fournisseurs. ✅ [VÉRIFIÉ: explore_functional_unit]\n"
    "La table VendTable contient les données maîtres. ✅ [VÉRIFIÉ: get_sql_model/VendTable]\n"
)

JUDGMENT_MD = (
    "Les approbations sont souvent configurées en 3 niveaux. 🔶 [JUGEMENT — à confirmer]\n"
)

MIXED_MD = VERIFIED_MD + JUDGMENT_MD + (
    "La sécurité est gérée par APs. ✅ [VÉRIFIÉ: get_security_links/AP]\n"
)

# A bare factual-looking sentence with no tag (should surface as unverified heuristic).
UNTAGGED_FACTUAL = "La table CustTable contient les données clients.\n"


# ---------------------------------------------------------------------------
# parse_grounding_tags
# ---------------------------------------------------------------------------


def test_parse_verified_tags():
    claims = parse_grounding_tags(VERIFIED_MD)
    assert len(claims) == 2
    assert all(c.kind == "verified" for c in claims)
    assert claims[0].source == "explore_functional_unit"
    assert claims[1].source == "get_sql_model/VendTable"


def test_parse_judgment_tags():
    claims = parse_grounding_tags(JUDGMENT_MD)
    assert len(claims) == 1
    assert claims[0].kind == "judgment"
    assert claims[0].source == ""


def test_parse_mixed_tags_order_preserved():
    claims = parse_grounding_tags(MIXED_MD)
    kinds = [c.kind for c in claims]
    assert kinds.count("verified") == 3
    assert kinds.count("judgment") == 1


def test_parse_no_tags_returns_empty():
    assert parse_grounding_tags("Aucun tag ici.\n") == []


def test_parse_claim_carries_line_number():
    md = "Ligne un.\nLe module AP. ✅ [VÉRIFIÉ: explore_functional_unit]\nLigne trois.\n"
    claims = parse_grounding_tags(md)
    assert claims[0].line == 2


# ---------------------------------------------------------------------------
# build_grounding_registry
# ---------------------------------------------------------------------------


def test_registry_contains_only_verified():
    claims = parse_grounding_tags(MIXED_MD)
    registry = build_grounding_registry(claims)
    assert all(r["kind"] == "verified" for r in registry)
    assert len(registry) == 3


def test_registry_entry_fields():
    claims = parse_grounding_tags(VERIFIED_MD)
    reg = build_grounding_registry(claims)
    entry = reg[0]
    assert "source" in entry and "line" in entry and "snippet" in entry
    assert entry["source"] == "explore_functional_unit"


def test_registry_empty_when_no_verified():
    claims = parse_grounding_tags(JUDGMENT_MD)
    assert build_grounding_registry(claims) == []


# ---------------------------------------------------------------------------
# find_unverified_claims
# ---------------------------------------------------------------------------


def test_find_unverified_includes_judgment_tags():
    issues = find_unverified_claims(JUDGMENT_MD)
    assert len(issues) >= 1
    assert any(i["kind"] == "judgment" for i in issues)


def test_find_unverified_includes_bare_table_references():
    """Heuristic: sentences containing 'table <Name>' or 'la table' with no following tag."""
    issues = find_unverified_claims(UNTAGGED_FACTUAL)
    assert len(issues) >= 1
    assert any("CustTable" in i["text"] or "table" in i["text"].lower() for i in issues)


def test_find_unverified_does_not_flag_verified_sentences():
    """A sentence ending with ✅ tag should NOT appear in find_unverified_claims."""
    issues = find_unverified_claims(VERIFIED_MD)
    # Lines that carry ✅ must not be in the issues list
    for issue in issues:
        assert "✅" not in issue["text"]


def test_find_unverified_empty_on_clean_doc():
    """No tags AND no heuristic pattern triggers → no issues."""
    clean = "Voici un commentaire général sans affirmation factuelle.\n"
    issues = find_unverified_claims(clean)
    assert issues == []


from d365fo_agent.spec_grounding import validate_fdd


# ---------------------------------------------------------------------------
# validate_fdd
# ---------------------------------------------------------------------------

_MINIMAL_FDD = """
## Contexte et objectif
Description du projet. ✅ [VÉRIFIÉ: explore_functional_unit]

## Périmètre
In: rapprochement. Out: paiements.

## Processus métier
As-is / to-be. 🔶 [JUGEMENT — à confirmer]

## Exigences
REQ-001: …

## Fit-Gap
Analyse. ✅ [VÉRIFIÉ: element_exists/VendSettlement]

## Conception fonctionnelle
Description.

## Objets AOT impactés
VendTable. ✅ [VÉRIFIÉ: find_relations/VendTable]

## Modèle de données
Schéma. ✅ [VÉRIFIÉ: get_sql_model/VendTable]

## Sécurité
Rôles. ✅ [VÉRIFIÉ: get_security_links/AP]

## Intégrations et OData
Aucune.

## États et reports
Aucun.

## Hypothèses et risques
À confirmer.

## Annexe : registre de grounding
| Ligne | Source | Snippet |
|---|---|---|
| 3 | explore_functional_unit | Description du projet. |
"""


def test_validate_fdd_ok_on_complete_doc():
    report = validate_fdd(_MINIMAL_FDD)
    assert report["ok"] is True
    assert report["missing_sections"] == []
    assert report["has_grounding_appendix"] is True
    assert report["verified_count"] >= 5
    assert report["judgment_count"] == 1


def test_validate_fdd_detects_missing_sections():
    no_security = _MINIMAL_FDD.replace("## Sécurité\nRôles. ✅ [VÉRIFIÉ: get_security_links/AP]\n", "")
    report = validate_fdd(no_security)
    assert report["ok"] is False
    assert any("sécurité" in s.lower() for s in report["missing_sections"])


def test_validate_fdd_detects_missing_appendix():
    no_appendix = _MINIMAL_FDD.replace("## Annexe : registre de grounding", "## Annexe : divers")
    report = validate_fdd(no_appendix)
    assert report["ok"] is False
    assert report["has_grounding_appendix"] is False


def test_validate_fdd_custom_required_sections():
    report = validate_fdd("## Contexte et objectif\n\nTexte.\n",
                          required_sections=["contexte"])
    # Missing appendix so ok=False, but missing_sections is empty.
    assert report["missing_sections"] == []
    assert report["has_grounding_appendix"] is False


def test_validate_fdd_counts_tags_correctly():
    md = (
        "✅ [VÉRIFIÉ: t1]\n"
        "✅ [VÉRIFIÉ: t2]\n"
        "🔶 [JUGEMENT — à confirmer]\n"
        "🔶 [JUGEMENT — à confirmer]\n"
        "🔶 [JUGEMENT — à confirmer]\n"
        "## Annexe : registre de grounding\n"
    )
    report = validate_fdd(md, required_sections=[])
    assert report["verified_count"] == 2
    assert report["judgment_count"] == 3


# ---------------------------------------------------------------------------
# Acceptance example — synthetic mini-FDD round-trip
# ---------------------------------------------------------------------------

_ACCEPTANCE_FDD = """\
## Contexte et objectif

Le module Accounts Payable (AP) gère les factures fournisseurs. ✅ [VÉRIFIÉ: explore_functional_unit]

## Périmètre

In: rapprochement factures/paiements. Out: comptabilisation des écarts.

## Processus métier

Les approbations sont souvent configurées en 3 niveaux de validation. 🔶 [JUGEMENT — à confirmer]

## Exigences

REQ-001: Le système doit rapprocher automatiquement les factures et les paiements.

## Fit-Gap

| REQ | Standard | Source | Écart |
|---|---|---|---|
| REQ-001 | Fit ✅ [VÉRIFIÉ: element_exists/VendSettlement] | VendSettlement | — |

## Conception fonctionnelle

La table VendTable contient les données maîtres fournisseurs. ✅ [VÉRIFIÉ: get_sql_model/VendTable]

## Objets AOT impactés

VendTable, VendTrans. ✅ [VÉRIFIÉ: find_relations/VendTable]

## Modèle de données

Colonnes: AccountNum, Name, Currency. ✅ [VÉRIFIÉ: get_sql_model/VendTable]

## Sécurité

Rôle AP Clerk. ✅ [VÉRIFIÉ: get_security_links/AP]

## Intégrations et OData

Entité VendorV2. ✅ [VÉRIFIÉ: get_entity_exposure/VendorV2]

## États et reports

Aucun état standard impacté. 🔶 [JUGEMENT — à confirmer]

## Hypothèses et risques

H-01: Le paramétrage des groupes de rapprochement est déjà en place. 🔶 [JUGEMENT — à confirmer]

## Annexe : registre de grounding

| Ligne | Source | Extrait |
|---|---|---|
| 3 | explore_functional_unit | Le module AP gère les factures fournisseurs. |
| 11 | element_exists/VendSettlement | REQ-001 Fit |
| 15 | get_sql_model/VendTable | La table VendTable contient… |
| 17 | find_relations/VendTable | VendTable, VendTrans |
| 19 | get_sql_model/VendTable | Colonnes: AccountNum… |
| 21 | get_security_links/AP | Rôle AP Clerk |
| 23 | get_entity_exposure/VendorV2 | Entité VendorV2 |
"""


def test_acceptance_parse_grounding_tags():
    """7 ✅ verified + 3 🔶 judgment tags in the acceptance FDD."""
    claims = parse_grounding_tags(_ACCEPTANCE_FDD)
    verified = [c for c in claims if c.kind == "verified"]
    judgments = [c for c in claims if c.kind == "judgment"]
    assert len(verified) == 7, f"Expected 7 verified, got {len(verified)}"
    assert len(judgments) == 3, f"Expected 3 judgments, got {len(judgments)}"


def test_acceptance_build_grounding_registry():
    """Registry contains exactly the 7 verified claims with correct sources."""
    claims = parse_grounding_tags(_ACCEPTANCE_FDD)
    registry = build_grounding_registry(claims)
    assert len(registry) == 7
    sources = {r["source"] for r in registry}
    assert "explore_functional_unit" in sources
    assert "element_exists/VendSettlement" in sources
    assert "get_sql_model/VendTable" in sources
    assert "find_relations/VendTable" in sources
    assert "get_security_links/AP" in sources
    assert "get_entity_exposure/VendorV2" in sources


def test_acceptance_find_unverified_claims():
    """3 explicit 🔶 judgment tags and 0 untagged table heuristic hits (all tables carry ✅)."""
    issues = find_unverified_claims(_ACCEPTANCE_FDD)
    judgment_issues = [i for i in issues if i["kind"] == "judgment"]
    assert len(judgment_issues) == 3
    # The VendTable bare-table sentences all carry ✅, so no heuristic hits for them.
    heuristic_hits = [i for i in issues if i["kind"] == "heuristic"]
    assert len(heuristic_hits) == 0, (
        f"Unexpected heuristic hits: {heuristic_hits}"
    )


def test_acceptance_validate_fdd():
    """Complete acceptance FDD passes validate_fdd with ok=True."""
    report = validate_fdd(_ACCEPTANCE_FDD)
    assert report["ok"] is True, f"validate_fdd failed: {report}"
    assert report["missing_sections"] == []
    assert report["has_grounding_appendix"] is True
    assert report["verified_count"] == 7
    assert report["judgment_count"] == 3
