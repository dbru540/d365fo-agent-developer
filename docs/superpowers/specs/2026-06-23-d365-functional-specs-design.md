# Design — Capacité « spécifications fonctionnelles » ancrées pour D365 F&O

**Date** : 2026-06-23
**Statut** : design validé (cadrage), prêt pour plan d'implémentation
**Baseline** : `d365fo-agent-developer` v0.9.0 (PyPI), 27 outils MCP, 194 tests verts, stdlib-only

## 1. But

Rendre le serveur MCP capable d'aider à **créer des spécifications fonctionnelles** D365 F&O — pas
seulement générer du code. Aujourd'hui le serveur ancre les faits **techniques** (métadonnées AOT,
modèle SQL, unités fonctionnelles, sécurité, relations) mais n'a **aucun corpus du comportement
fonctionnel** : le raisonnement fonctionnel vient de l'entraînement du modèle (non ancré). On comble
ça par deux features, livrées en deux phases.

## 2. Décisions de cadrage (actées)

| Sujet | Décision |
|---|---|
| Workflow cible | **Agent autonome** : le document de spec structuré EST le livrable |
| Specs internes | **Word (.docx)** — extraction **stdlib** (`zipfile` + `xml.etree` sur `word/document.xml`), pas de `python-docx` |
| Gabarit | **Structure FDD standard** (figée en §6, à confirmer) |
| Format de sortie | **Markdown** (source de vérité, citations inline) + **export .docx** (skill docx) |
| Scope MS Learn | **Tout D365 F&O** |
| Stockage/recherche | **FTS5 par défaut** (0 dép) + **vecteurs pré-construits livrés en asset** ; sémantique = **extra optionnel ONNX**, dégradation gracieuse |
| Livraison feature 2 | **Skill/workflow** + nouveaux **outils MCP** (`search_docs`/`get_docs`) |

### Nuance embeddings (importante)
L'asset pré-construit élimine le ré-embedding du **gros corpus MS Learn**, pas le besoin d'un
embedder local au runtime : la **requête** est dynamique et les **specs .docx internes** sont
embeddées **localement** (privées). Tous les vecteurs d'un même espace doivent venir du **même
modèle** → on fige **un** modèle ONNX petit/multilingue, utilisé partout (MS Learn offline → asset ;
specs internes en local ; requêtes au runtime). Le sémantique reste un **extra `[semantic]`** ;
**FTS5 reste le défaut**.

### Licence
L'asset livré ne contient que **vecteurs + citations (URL/chemin)**, **pas le texte MS Learn** →
aucune redistribution de contenu (respect du handoff). Le texte vient (a) du clone local du markdown
public `MicrosoftDocs` et (b) des .docx de l'utilisateur. Cohérent avec « l'utilisateur construit
son index » (pattern de l'index AOT et de `knowledge_fetch`).

## 3. Architecture retenue (Approche A)

**Index documentaire séparé + skill d'orchestration.** Alternatives écartées :
- **B** (étendre `D365Index` avec une source docs, DB unique) — mélange chunks de prose et lignes de
  symboles, pollue le schéma ; vecteurs seulement sur une partie. La frontière *prose vs symboles*
  est explicite dans le projet (vecteurs sur prose, jamais sur symboles AOT).
- **C** (skill de spec d'abord, grounding plus tard) — contredit le but (ancrer le fonctionnel).

Patterns copiés : `guidance.py` (loader + 3 outils MCP) et `index_store.py` (`D365Index` FTS5,
stdlib) ; `knowledge_fetch.py` (asset téléchargeable, hors paquet).

## 4. Phase 1 — Doc grounding

### Modules neufs (`src/d365fo_agent/`)
- **`doc_ingest.py`** — extraction → chunks.
  - MS Learn : depuis le **markdown public GitHub `MicrosoftDocs`** (pas de scraping HTML).
  - .docx internes : `zipfile` + `xml.etree` (stdlib).
  - Chunking par section ; métadonnées par chunk : `title`, `source_url`/`source_path`, `module`,
    `platform` (`d365fo`/`ax2012`/`both`), `origin` (`mslearn`/`internal`).
- **`doc_store.py`** — `DocIndex` : SQLite **FTS5** sur les chunks (texte stocké localement) + table
  vecteurs optionnelle (`chunk_id` → blob). API : `search(query, *, platform=None, module=None,
  origin=None, limit=...)` (BM25 ; rerank vectoriel si vecteurs présents), `get(chunk_id)`, `stats`.
  Dégrade en FTS5-seul sans l'extra.
- **`embed.py`** (extra `[semantic]`) — wrapper ONNX (fastembed) : `embed(texts) -> list[vector]`.
  Absent → pas de vecteurs, FTS5 seul. Aucune dépendance torch, aucune sortie réseau.

### CLI
- `build-doc-index --mslearn <clone-md> --internal <dossier-docx> --db docs.db [--rebuild]`
- `fetch-doc-vectors [--url <asset>] [--db docs.db]` (pattern `knowledge_fetch`)

### Outils MCP
- `search_docs(query, platform?, module?, origin?, limit?)` → liste de chunks classés, **chaque
  résultat porte sa citation source** (URL ou chemin + titre de section).
- `get_docs(chunk_id)` → section complète + métadonnées + citation.
- `docs_stats()` → couverture (nb chunks par origine/module, vecteurs présents ou non).

### Schéma `docs.db` (esquisse)
```
chunks(id, doc_id, origin, platform, module, title, source_ref, ord, text)
chunks_fts(text)  -- FTS5, contentless lié à chunks
chunk_vectors(chunk_id, model, dim, vector)  -- optionnel
doc_meta(key, value)  -- modèle d'embedding utilisé, versions, dates
```

## 5. Phase 2 — Workflow « spécification fonctionnelle »

**Skill `functional-spec`** orchestrant, dans l'ordre :
1. `explore_functional_unit` (domaine → tables/entités cœur)
2. objets impactés : `find_relations` / `find_references` / `find_reverse_references`
3. fit-gap : `element_exists` / `get_entity_exposure` / **`search_docs`** (standard couvre-t-il déjà ?)
4. sécurité : `get_security_links`
5. modèle de données : `get_sql_model`
6. règles de conception : `get_guidance`
7. rédaction dans le gabarit FDD
8. export .docx (skill docx)

## 6. Gabarit FDD (à confirmer)
Contexte/objectif · Périmètre (in/out) · Processus métier (as-is/to-be) · Exigences (numérotées,
traçables) · **Fit-Gap** · Conception fonctionnelle · **Objets AOT impactés** · **Modèle de
données** · **Sécurité** (rôles/devoirs/privilèges) · Intégrations/OData · États & reports ·
Hypothèses/risques/questions ouvertes · **Annexe : registre de grounding**.

## 7. Contrat anti-hallucination (cœur)
- Chaque affirmation taguée inline : ✅ **`[VÉRIFIÉ: outil/source]`** vs 🔶 **`[JUGEMENT — à
  confirmer]`**.
- **Annexe registre de grounding** : chaque fait → appel d'outil et/ou citation doc (URL/chemin).
- Tout raisonnement fonctionnel non ancré est **explicitement** marqué jugement du modèle.
- Un fait « vérifié » ne l'est que s'il provient du serveur (index/outil) ou d'un chunk doc cité.

## 8. Tests
- Extraction .docx (stdlib) ; chunking ; `DocIndex` FTS5 + **dégradation sans extra**.
- `search_docs` / `get_docs` (citations présentes et correctes).
- Orchestration de la skill sur un cas synthétique (faits ancrés vs jugement séparés).
- Cible : conserver les ~194 tests verts + nouveaux.

## 9. Ship discipline (rappel)
venv neuf TestPyPI → PyPI → tag ; bump `pyproject` ; globs `package-data` ; **jamais de nom client
commité** (`git grep --cached`) ; auth `GH_TOKEN=$(wsl gh auth token)`. L'asset vecteurs est
découplé du code (tag dédié, ex. `doc-vectors-v1`), hors wheel.

## 10. Questions ouvertes (à lever au plan d'implémentation)
- Emplacement exact des .docx internes (local / SharePoint / Drive) + dossier de travail.
- Choix précis du modèle ONNX multilingue (taille vs qualité FR↔EN ; ex. e5-small / bge-small).
- Quel repo/sous-arbre `MicrosoftDocs` pour le périmètre F&O complet, et fréquence de rafraîchissement.
- Validation finale des sections du gabarit FDD.
- Format exact des tags de grounding dans le Markdown (à figer pour parsing/contrôle).

## 11. Séquencement
**Phase 1 d'abord** (doc grounding : la fondation), **puis Phase 2** (workflow de spec qui la
consomme). Chaque phase = son propre plan d'implémentation.
