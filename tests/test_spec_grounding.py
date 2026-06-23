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
