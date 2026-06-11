# Plan — Solution opérationnelle : serveur MCP D365/X++ autonome

## ✅ FAIT — Polish capacité : générateur `form` + fix champ enum

- [x] Famille `form` : AxForm SimpleList minimal mais **compilable** (`_render_form`) — SourceCode + 1 AxFormDataSource + Design avec les 3 enfants requis du pattern (**ActionPane + CustomFilterGroup/QuickFilter + Grid**, découverts en itérant contre xppc) + 1 contrôle string par champ. specs identité+mapped_fields ; validate FAMILY_ROOT `form`→AxForm + règle curée. Forms riches = scaffold_object(AxForm).
- [x] Fix enum : champ de table sur BASE enum → `<EnumType>` (pas `<ExtendedDataType>`), via `resolver.enum_name` (index `AxEnum` + `_KNOWN_BASE_ENUMS={NoYes,Gender,Weekday,Timezone}` car les enums kernel n'ont pas de XML dans le corpus). Tests +2 (total **156**). Ruff clean.
- [x] PROUVÉ E2E : spec (table avec champ enum NoYes + form liée) → générer → `compile-generated` → **succeeded, 0 erreur, PLD restauré**. ~22 familles déterministes.

## ⏳ RESTE — EXPÉDITION (actions utilisateur, comptes requis)
- [ ] Reconstruire le wheel : `python -m build` (dist obsolète — manque class/table/form/compile_generated).
- [ ] Publier PyPI : `python -m twine upload dist/*` (compte ; vérifier nom `d365fo-agent` libre).
- [ ] Héberger l'index standard `.db.gz` (GitHub release) + `DEFAULT_KNOWLEDGE_URL` dans `knowledge_fetch.py`.
- [ ] Remplir email auteur + URLs `your-org` dans `pyproject.toml` ; `git init` du toolkit.

## ✅ FAIT — #1 boucle générer→compiler + #2 validation par un vrai ticket

- [x] #1 : `XppCompiler.compile_overlay(model, overlays)` — overlaie les artefacts générés dans leur modèle (PLD), compile au vrai `xppc`, **restaure toujours** (try/finally). Outil MCP `compile_generated` (**21 outils**) + CLI `compile-generated`. Dé-risqué + testé (unit overlay/restore/restore-sur-exception + intégration réelle : classe sonde → exit 0 → PLD propre).
- [x] Stubs de méthodes **compilables** : `_method_stub_body` (`next` pour CoC, `<RetType> _ret; return _ret;` sinon) — une classe générée compile AVANT que l'agent remplisse la logique. `_parse_methods` préserve `static`/`final`.
- [x] #2 : vrai ticket E2E prouvé — spec (table + classe) → générer le set → valider → `compile-generated` (overlay→xppc→restore) → **succeeded, 0 erreur, PLD restauré** (~5s). North Star démontré.
- [x] Tests : +4 (total **154**). Ruff clean. Mémoire/docs MAJ.
- [ ] Finding ouvert (mineur) : générateur `table` émet `<ExtendedDataType>` pour les champs enum (devrait être `<EnumType>`).

## ✅ FAIT — Combler les trous « développer une classe / table / ensemble depuis une spec »

But du projet : un dev X++ dans Claude Code/Codex demande de développer une classe/form/ensemble depuis une spec, l'agent remplit au maximum.
- [x] Familles déterministes **`class`** (AxClass autonome : déclaration + stubs de méthodes depuis la spec — l'agent remplit les corps) et **`table`** (AxTable autonome : déclaration + champs typés via le résolveur EDT + field-groups standard + conteneurs index/relations vides). `generator._render_class`/`_render_table`, identités `specs.py`, `validate.FAMILY_ROOT` + règle curée AxTable. → ~20 familles déterministes.
- [x] Répartition des rôles confirmée : le toolkit échafaude la STRUCTURE + ancre + vérifie ; l'AGENT écrit la LOGIQUE X++ dans les stubs. Forms = scaffold+adapter ; ensembles = specs multi-artefacts + patch-set.
- [x] Tests : +2 (total **150**). Prouvé E2E : un spec multi-artefacts → un ENSEMBLE câblé (AxTable + AxClass + AxSecurityPrivilege) généré ensemble, chacun valide. Ruff clean. Docs/mémoire MAJ.

## ✅ FAIT — Packaging pour distribution (MCP server pip-installable, connaissance embarquée)

But réel : `pip install` un serveur MCP qui CONNAÎT déjà X++, sans re-fournir un repo à chaque fois.
- [x] `pyproject.toml` durci (v0.3.0, licence MIT, readme, classifiers, urls, `package-data`) + `LICENSE` (MIT).
- [x] Données embarquées (`src/d365fo_agent/data/` : méthodologie, règles, profil de types par défaut) résolues via `importlib.resources` (`packaged_data_dir()`) — corrige le bug « chemins relatifs à l'arbre source » qui cassait après `pip install`.
- [x] Modèle de distribution : moteur en wheel ~90 Ko ; index standard ~100 Mo en **asset téléchargeable** → `knowledge_fetch.fetch_knowledge` + CLI `fetch-knowledge` (urllib+gzip → `~/.d365fo-agent/d365fo.db`). `serve-mcp` défaut `--db`=cache, `--repo-root`/`--rules` OPTIONNELS ; `build-index` standard-seul sans `--repo-root`.
- [x] Tests : +6 (total **148**). PROUVÉ : wheel construit, installé dans un **venv neuf** (hors source) → méthodologie+profils chargés depuis le bundle, 20 outils, `twine check` PASSED. README distribution (install + fetch/build + branchement Claude Code & Codex).
- [ ] **Décisions/actions utilisateur** (flaggées) : dispo du nom PyPI + `twine upload` (compte) ; repo GitHub + release pour héberger l'index .db.gz + `DEFAULT_KNOWLEDGE_URL` ; redistribuer un index standard OU laisser chacun le construire ; remplir email auteur / URLs `your-org`.

## ✅ FAIT — #2 : linter détecte les mauvais types de champs sur EDT standard

- [x] `linter._expected_field_type(edt, index, roots)` délègue à `knowledge.resolve_edt_field_type` (lit le `i:type`) → `field-type-matches-edt` attrape les EDT **standard** (tous en `AxEdt` générique), plus seulement les EDT custom à dossier sous-typé. `LintContext.roots` ajouté ; appels lint MCP passent `self.file_roots` ; CLI `lint --repo-root/--packages-root`. Dégrade sans roots (pas de faux positif).
- [x] Tests : +3 (total **142**). Prouvé E2E : champ `AmountCur` (Real) déclaré `AxTableFieldString` → signalé ; `AxTableFieldReal` → propre. Générateur produit le bon type ET linter attrape le mauvais : symétrie fermée. Ruff clean. Mémoire/lessons MAJ.

## ✅ FAIT — Polish optionnel #3 (templates déterministes) + #4 (scaffold spec-aware)

- [x] #3 : générateurs spec→XML déterministes pour **enum, enum-extension, edt, data-entity-view-extension, view** (`generator.py` + `specs.py` : familles, parsers `enum_values`/`mapped_fields`, props EDT subtype/string_size/extends/reference_table ; `validate.FAMILY_ROOT`). Formes XML ancrées sur de vrais exemples (BABInvoiceStatus, LedgerPostingType.*, BABString100, BankAccountEntity.*, BABCompanyView). `generate_from_spec` couvre ~18 familles ; la longue traîne reste en scaffold.
- [x] #4 : `scaffold_object` spec-aware — `properties={Element:value}` pose des nœuds top-level sur le squelette cloné (remplace si présent, insère après `<Name>` sinon) ; arg MCP `properties` + CLI `scaffold --set K=V`.
- [x] Tests : +6 (total **139**). Prouvé E2E : AxEnum généré → valide contre le profil appris (rule_source=learned) ; scaffold AxTile --set Label insère le nœud. Ruff clean. Mémoire/docs MAJ.

## ✅ FAIT — Validation universelle (générer n'importe quel objet AVEC confiance)

`validate_xml` ne validait structurellement que ~18 racines ; pour le reste = check générique (Name seul) → un `AxView` tronqué passait à tort.
- [x] `type_profile.py` : `build_type_profiles` échantillonne ~200 exemples réels/type, apprend les enfants quasi-universels (≥95% → requis) / fréquents (≥40% → recommandés). Persisté dans `.omx/index/aot-type-profiles.json` (**71 types**) via CLI `build-type-profiles`. `index.paths_by_type` ajouté.
- [x] `validate.py` : résolution **curé → profil appris → générique** + champ `rule_source`. Serveur MCP auto-charge le JSON (propriété `type_profiles`, cache), tool `validate_xml` le passe ; CLI `validate-xml --profiles`.
- [x] Tests : +5 (total **133**). Prouvé E2E : `AxView` tronqué → signale 8 enfants requis manquants (Fields/Relations/ViewMetadata…) ; sans profil il passait. Règles apprises correctes (AxKPI→Goal/Measurement/Value, AxWorkflowApproval→Approve/Deny/Document). Docs + mémoire + lessons MAJ. Ruff clean.
- Note : la génération déterministe reste ~13 familles **par choix** — « générer n'importe quel objet » = `scaffold_object` (clone d'exemple réel) + grounding + cette chaîne de vérif, PAS 72 templates.

## ✅ FAIT — Couvrir TOUT type d'objet AOT (grounding universel + `scaffold_object`)

Demande : « être capable d'aider à coder tout type d'objet dans l'AOT ». Cause racine trouvée : l'indexeur avait une **whitelist** (`AOT_TYPE_DIRECTORIES`, 25 types) qui laissait tomber ~50 types / ~66k objets en silence.
- [x] **DEUX whitelists supprimées** (`index_store.AOT_TYPE_DIRECTORIES` côté standard + `indexer.SUPPORTED_ARTIFACT_TYPES` côté custom/`src`) → indexe **tout dossier `Ax*`**. Index canonique reconstruit : **233 688 artefacts / 72 types** (était 166 988 / 25) ; custom (depuis `src/xplusplus/models`) 1152→**1372 / 16→36 types** (énums, EDT, extensions custom enfin captés). Les DEUX sources servent : `src` (source X++ éditable, résolu en premier pour le custom) + PackagesLocalDirectory (standard + déployé). `extension-of` généralisé à toutes les `*Extension`.
- [x] `scaffold_object` (outil MCP **#20** + CLI `scaffold` + `knowledge.scaffold_object` + `index.sample_by_type`/`list_types`) : clone un vrai exemple du corpus de N'IMPORTE quel type comme squelette renommé → « aide-moi à coder un <type> » pour tout l'AOT, zéro template par type. `index_stats` expose `supported_object_types` (les 72 types).
- [x] Tests : +5 (total **128**). Prouvé E2E : scaffold d'un `AxWorkflowApproval` (type auparavant invisible) → exemple réel cloné + renommé. Docs (mcp-server.md) + mémoire + lessons MAJ. Ruff clean.

## ✅ FAIT — Dernier barreau : compile X++ réel (`compile_model`, SANS Docker)

L'utilisateur a proposé Docker → fausse piste : moteur **Linux**, or `xppc.exe` est un assembly **.NET Framework Windows**. On est déjà SUR l'hôte Windows et le compilateur est là.
- [x] `build.py` : `XppCompiler` (drive `PackagesLocalDirectory/bin/xppc.exe` : `-metadata -modelmodule -output -referenceFolder -log [-RunAppcheckerRules] [-xref]`) + `parse_xppc_log` (log → diagnostics structurés severity/category/element/location) + `CompileResult`. `status="unavailable"` si xppc absent (dégradation gracieuse, jamais de crash). `BuildRunner` MSBuild conservé.
- [x] Outil MCP `compile_model` (**19 outils**) — barreau 3 de l'échelle de vérification ; CLI `compile-model`. Méthodologie §10 + mcp-server.md MAJ.
- [x] Tests : +5 (total **123**). Parseur testé sur 2 vrais logs ; chemin `unavailable` ; **compile réel skip-gardé** (BABSuspendDimensionPerLegalEntity → exit 0, 0 erreur). CLI prouvée sur le modèle en échec (diagnostics structurés, exit 1). Ruff clean.
- Constat : le compile vert existe (le « miroir partiel » était une fausse alerte — l'assembly Commerce est présent) ; l'échec de BABCountryRegionVendBankAccount est un NRE spécifique au modèle.

## ✅ FAIT — Typage de champ correct À LA GÉNÉRATION (gap fermé à la source)

- [x] `knowledge.resolve_edt_field_type(index, edt, roots)` : résout l'EDT → `AxTableField*` en LISANT le `i:type` du XML (constat : le corpus standard indexe TOUS les EDT sous le dossier générique `AxEdt`, sous-type seulement dans le XML — le mapping par dossier ne suffit pas).
- [x] Générateur : `_table_field_type_for_edt(edt, resolver)` + `FieldTypeResolver` callable threadé via `render_artifact`/`merge_artifact` (create ET merge) ; `generate_from_spec_file(db_path=…)` construit le résolveur. CLI `generate-from-spec --db` ; le tool MCP passe son propre db. Fallback heuristique inchangé sans index.
- [x] Tests : +2 (total **118**). Prouvé E2E sur le vrai index : `AmountCur→AxTableFieldReal`, `TransDate→AxTableFieldDate` (les deux silencieusement `String` sans `--db`). Docs (méthodologie §5) + mémoire MAJ. Ruff clean.
- [ ] Suite logique (non démarrée) : donner au linter le même `resolve_edt_field_type` (nécessite `file_roots` dans `LintContext`) pour qu'il DÉTECTE aussi les mauvais types sur les EDT standard.

## ✅ FAIT — Câblage sécurité `wire_security` (suite directe de derive_entity)

Un privilège ne donne aucun accès tant qu'il n'est pas atteignable depuis un rôle via une duty.
- [x] `security_wiring.py` : `wire_security` (orchestrateur) + 4 builders `build_duty_extension`/`build_role_extension`/`build_duty`/`build_role`. Extension-first par défaut (`*Extension` sur objets standard, nom `<StdObject>.<suffixe>`), ou `extend_*=false` → nouvelle duty/role custom. Les 4 formes XML ancrées sur de vrais artefacts du corpus (BAB-ExportBFC, BABCountryRegionVendBankAccount, BABGeneralLedger). Renvoie la chaîne `privilège→duty→rôle`.
- [x] Outil MCP `wire_security` (**18 outils**) : vérifie la cible d'extension par TYPE via l'index et AVERTIT (ne bloque pas — référencée par nom seul). Commande CLI `wire-security`. Familles `security-duty`/`security-role` ajoutées à `validate.py`.
- [x] Tests : +14 (total **116, 0 erreur, 11 skip**). Prouvé end-to-end sur le vrai index : cibles custom vérifiées (`BABLedgerAccountingManager`/`BABLedgerChartOfAccountsMaintain`) → propre ; cibles standard non indexées → produit + avertit. Docs MAJ (`mcp-server.md` exemple OData complet + `x++-methodology.md` §6). Mes fichiers : ruff clean.

## ✅ FAIT — Dérivation d'entité OData (scénario "exposer une entité standard")

Pattern "dupliquer une entité standard, la rendre publique, relabel, sécuriser" :
- [x] `entity_derive.py` : `derive_public_entity` CLONE le XML réel (289 champs préservés, pas un stub → ferme vraiment S03) + mute Name/IsPublic/Public*Name/Label/DataManagement + renomme la classe ; `build_entity_privilege` (forme `DataEntityPermissions` ancrée sur un exemple réel du corpus).
- [x] Outil MCP `derive_entity` (17 outils) : résout la source via l'index, clone, construit le privilège, valide + lint les deux, + checklist de revue. Commande CLI `derive-entity`.
- [x] Tests : +13 (total 102). Vérifié sur la vraie `CustCustomerV3Entity` → 289 champs, lint 0 erreur. Docs MAJ (exemple de bout en bout). Ruff clean.

## ✅ FAIT — Couche de règles X++ formalisée (linter)

Écart "prose vs machine-enforced" fermé : règles de codage X++ appliquées automatiquement.
- [x] `config/x++-rules.json` — données : préfixes + activation/sévérité/desc par règle (modèle ESLint).
- [x] `linter.py` — moteur + 7 checks (2 index-backed) : naming-prefix, label-not-literal, field-type-matches-edt (gap `bad-field-type` détecté), extension-target-exists (anti-hallucination), no-legacy-reference, privilege-grant-explicit, data-entity-completeness (gap S03).
- [x] `AOT_TYPE_DIRECTORIES` élargi (famille EDT) ; index reconstruit (166 988).
- [x] Outil MCP `lint_artifact` (16 outils) + auto-lint dans `generate_from_spec` ; commande CLI `lint`.
- [x] Tests : +16 (total 89, 76 pass, 11 skip graphe, 2 MAX_PATH env). Docs MAJ. Ruff clean.

---

## ✅ STATUT : LIVRÉ ET OPÉRATIONNEL (build autonome)

- **Env réparé** : `graphify` rendu optionnel (import paresseux), `pyproject` >=3.11 + extras, CLI tourne.
- **Index SQLite FTS5** (`index_store.py`) : **166 988 artefacts** indexés (1152 custom + 165 836 standard) en ~9s. `exists()` = anti-hallucination sur tout le corpus D365.
- **Couche connaissance** (`knowledge.py`) : signatures (CustTable → 193 champs réels), extension chains, security, entité, exemples.
- **Validation** (`validate.py`) : well-formedness + structure AOT par famille, offline.
- **Méthodologie** (`docs/x++-methodology.md`) : contrat de comportement servi par MCP.
- **Serveur MCP** (`mcp_server.py`) : JSON-RPC stdio stdlib pur, **15 outils** prescriptifs, testé in-process + subprocess.
- **CLI** : `build-index`, `serve-mcp`, `validate-xml` ajoutés.
- **Tests** : +25 (total 73). 60 pass, 11 skip (graphe optionnel absent), **2 erreurs = Windows MAX_PATH** (pré-existant, confirmé, hors de mon code). Ruff : clean.
- **Docs** : `docs/mcp-server.md` (wiring Claude Code/Codex/Gemini), README mis à jour.
- **Understand-Anything** : cloné + buildé sous `_WORK/AI/tools/` (dashboard vite OK). Reste : l'utilisateur tape les 2 commandes `/plugin`.

Restes connus (non bloquants) : 2 tests MAX_PATH (activer LongPaths Windows ou base plus courte) ; compile/Best-Practice nécessitent un hôte Windows D365 (`build-project` planifie déjà).

---


**Objectif** : un serveur MCP vendor-neutral (Claude Code / Codex / Gemini) qui rend les LLM
autonomes pour générer du X++/D365 de haute qualité — faits symboliques exacts, relations
(graphe), exemples idiomatiques, méthodologie, et vérification — adossé à un index SQLite FTS5
persistant. Stdlib pur (aucune dépendance runtime), pour tourner partout.

Contraintes machine : Windows, Python 3.11.9, FTS5 OK, pas de pytest/ruff (on utilise
`python -m unittest`). `graphify` non installé → import à rendre optionnel.

## Décisions autonomes (pas de validation demandée)
- Index : **SQLite FTS5** (stdlib `sqlite3`), fichier `.omx/index/d365fo.db`. Pas de Postgres/pgvector en MVP.
- MCP : serveur **JSON-RPC 2.0 stdio en stdlib pur** (pas de package `mcp`) → portable, zéro install.
- `requires-python` abaissé à >=3.11 (réalité machine ; code compatible).
- Vecteurs/embeddings : **différés**, hors scope (cf. analyse précédente).
- Vérification : `validate_xml` (well-formedness + structure AOT) opérationnel maintenant ;
  compile/Best-Practice = adaptateur à dégradation gracieuse (nécessite env Windows D365).

## Phase 0 — Réparer l'environnement (débloquant)
- [ ] Rendre l'import `graphify` paresseux dans `graphify_runner.py` (imports dans la fonction).
- [ ] `pyproject.toml` : `requires-python>=3.11`, extras `[graph]` (graphify), `[dev]`.
- [ ] CLI s'importe et `inventory` tourne sur la machine.
- [ ] `python -m unittest` vert (baseline 42/45) — prouvé.

## Phase 1 — Index persistant SQLite FTS5 (`index_store.py`)
- [ ] Schéma : `artifacts`, `relations`, FTS5 `artifacts_fts`. Détection FTS5 + fallback LIKE.
- [ ] `build_from_catalog(catalog, db)` — corpus custom (riche : signature, source, flags).
- [ ] `index_packages_local(packages_root, db)` — walk path-based des packages standard
      (name=stem, type=dossier parent, package), batché, résumable, lançable en arrière-plan.
- [ ] API requête : `lookup_exact`, `search`, `relations_of`, `neighbors`, `stats`.
- [ ] Tests unittest.

## Phase 2 — Couche connaissance (`knowledge.py`)
- [ ] `get_signature(name)` — extrait méthodes/champs/EDT depuis le XML indexé.
- [ ] `get_extension_chain(name)` — chaîne extends/extension-of via relations+graphe.
- [ ] `get_security_links(name)` — privilèges/duties/roles/entry-points.
- [ ] `get_entity_exposure(name)` — flags OData/DM/public entity.
- [ ] `find_similar_examples(query)` — exact + FTS + graphe (pas de vecteurs).
- [ ] Tests unittest.

## Phase 3 — Vérification (`validate.py`)
- [ ] `validate_xml(xml, family)` — well-formedness + racine attendue + enfants requis par famille.
- [ ] Intégration adaptateur build (compile/BP) avec message de dégradation si pas d'env D365.
- [ ] Tests unittest.

## Phase 4 — Méthodologie (`docs/x++-methodology.md`)
- [ ] Règles : extension-first, CoC vs events, nommage, labels, sécurité, entités, anti-patterns.
- [ ] Exposée par MCP (`get_methodology` + resource).

## Phase 5 — Serveur MCP (`mcp_server.py`)
- [ ] JSON-RPC stdio : `initialize`, `tools/list`, `tools/call`, `resources/list`, `resources/read`.
- [ ] Outils : find_element, get_element_details, get_signature, find_references,
      find_reverse_references, get_extension_chain, get_security_links, get_entity_exposure,
      find_similar_examples, analyze_spec, generate_from_spec, validate_xml, get_methodology, index_stats.
- [ ] Descriptions **prescriptives** ("appelle ceci quand…") — anti-hallucination.
- [ ] Config via env (REPO_ROOT, RULES, DB, GRAPH). Tests unittest (in-process + subprocess).

## Phase 6 — CLI + packaging + docs
- [ ] CLI : `build-index`, `serve-mcp`, `validate-xml`.
- [ ] `docs/mcp-server.md` — wiring Claude Code (.mcp.json), Codex, Gemini CLI.
- [ ] README mis à jour. `python -m unittest` vert global.

## Critère "opérationnel"
- CLI tourne, index custom construit, serveur MCP répond à un handshake + tools/call réels,
  validate_xml fonctionne, méthodologie servie, suite de tests verte, doc de branchement fournie.
- Index standard (packages-local) lancé en arrière-plan (résumable).
