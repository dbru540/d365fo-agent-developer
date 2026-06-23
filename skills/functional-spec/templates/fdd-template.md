<!--
  FDD Template — D365 F&O Functional Design Document
  Skill: functional-spec | Version: 1.0 | Date: {{DATE}}
  Every factual claim MUST carry a grounding tag (see § Tag Contract below).
  ✅ [VÉRIFIÉ: <tool-or-source>]   = verified via MCP tool or doc chunk citation
  🔶 [JUGEMENT — à confirmer]      = model judgment — must be flagged for human review
-->

# Functional Design Document — {{TOPIC}}

**Date :** {{DATE}}
**Auteur :** {{AUTHOR}}
**Statut :** Brouillon

---

## Contexte et objectif

> Décrire le besoin métier, le périmètre du projet et les objectifs mesurables.

{{CONTEXTE}} ✅ [VÉRIFIÉ: explore_functional_unit]

---

## Périmètre

### Dans le périmètre

- {{IN_SCOPE_1}}

### Hors périmètre

- {{OUT_OF_SCOPE_1}}

---

## Processus métier

### As-is (situation actuelle)

{{AS_IS}} 🔶 [JUGEMENT — à confirmer]

### To-be (cible)

{{TO_BE}} 🔶 [JUGEMENT — à confirmer]

---

## Exigences

> Chaque exigence est numérotée et traçable vers le Fit-Gap.

| ID | Description | Priorité | Statut |
|---|---|---|---|
| REQ-001 | {{REQUIREMENT_1}} | Haute | Ouvert |

---

## Fit-Gap

> Pour chaque exigence, indiquer si le standard D365 couvre le besoin (Fit), nécessite une configuration (Config), ou un développement (Gap).

| REQ | Standard couvre ? | Source | Écart |
|---|---|---|---|
| REQ-001 | Fit ✅ [VÉRIFIÉ: element_exists/{{AOT_ELEMENT}}] | {{SOURCE}} | — |

---

## Conception fonctionnelle

> Description détaillée de la solution retenue, paramétrage, flux de données.

{{DESIGN}} 🔶 [JUGEMENT — à confirmer]

---

## Objets AOT impactés

> Tables, classes, formulaires, menus, énumérations, entités de données touchés.

| Objet | Type AOT | Opération | Source |
|---|---|---|---|
| {{TABLE_NAME}} | Table | Lire/Écrire | ✅ [VÉRIFIÉ: find_relations/{{TABLE_NAME}}] |

---

## Modèle de données

> Schéma des tables principales, clés primaires/étrangères, relations.

{{DATA_MODEL}} ✅ [VÉRIFIÉ: get_sql_model/{{TABLE_NAME}}]

---

## Sécurité

> Rôles, devoirs (duties) et privilèges impactés.

| Rôle / Devoir / Privilège | Action | Source |
|---|---|---|
| {{SECURITY_OBJECT}} | Accorder | ✅ [VÉRIFIÉ: get_security_links/{{MODULE}}] |

---

## Intégrations et OData

> Entités OData exposées, intégrations DMF, flux entrants/sortants.

{{INTEGRATIONS}} ✅ [VÉRIFIÉ: get_entity_exposure/{{ENTITY_NAME}}]

---

## États et reports

> SSRS, Power BI, rapports standards impactés.

{{REPORTS}} 🔶 [JUGEMENT — à confirmer]

---

## Hypothèses, risques et questions ouvertes

| # | Hypothèse / Risque | Statut | Responsable |
|---|---|---|---|
| H-01 | {{ASSUMPTION_1}} 🔶 [JUGEMENT — à confirmer] | Ouvert | — |

---

## Annexe : registre de grounding

> Ce registre est généré automatiquement depuis les tags ✅ du document.
> Chaque fait vérifié est tracé vers l'outil MCP ou le chunk documentaire source.

| Ligne | Source (outil / doc) | Extrait |
|---|---|---|
| _généré_ | _généré_ | _généré_ |
