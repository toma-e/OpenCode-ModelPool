# Guide de Développement : OpenCode-ModelPool 🤖

Ce document est le **point d'entrée de référence pour l'agent Antigravity** opérant sur le dépôt. Il garantit la continuité opérationnelle, la cohérence des choix techniques et le respect des conventions établies.

---

## 1. Vue d'Ensemble & Objectif

**OpenCode-ModelPool** attribue automatiquement le modèle LLM optimal à chaque agent d'un parc **OpenCode** en fonction :
1. De contraintes techniques d'aptitude (complexité 1-5, support d'outils, taille de contexte minimale, compatibilité des fournisseurs).
2. De contraintes économiques (gratuité préférée, plafond budgétaire mensuel, détection des risques de quota).
3. D'un mécanisme de **surclassement économique (`fallback`)** en l'absence de correspondance stricte.

---

## 2. Flux de Données & Architecture

```mermaid
flowchart TD
    OR["API Publique OpenRouter"] -->|src/fetcher.py| FET["src/fetcher.py"]
    OL["Ollama Local (:11434)"] -->|src/providers/ollama.py| FET
    DP["APIs Directes (Google, Mistral, Groq, Cerebras, Anthropic)"] -->|src/providers/direct.py| FET
    
    FET -->|Crée backup| BKP["data/backups/*.json"]
    FET -->|Génère| MJ["data/models.json"]
    
    ENV["Env / .env / auth.json"] -->|src/providers/detector.py| DET["src/providers/detector.py"]
    DET -->|src/providers/access.py (live probe)| PAC["data/provider_access.json"]
    
    AR["config/agents_requirements.json"] --> SVC["src/service.py"]
    MJ --> SVC
    PAC --> SVC
    
    SVC --> SEL["src/selector.py"]
    SVC --> BUD["src/budget.py"]
    SVC --> ROUT["src/providers/router.py"]
    SVC --> EXP["src/exporter.py"]
    
    EXP -->|Exporte| OC["config/opencode.json"]
    EXP -->|Exporte| REP["config/modelpool-report.json"]
    
    CLI["main.py"] --> SVC
    WEB["src/web.py"] --> SVC
```

---

## 3. Checklist d'Onboarding pour Nouvel Agent

Lorsqu'un nouvel agent prend en main ce projet, il doit :
1. **Consulter les fichiers clés :**
   - [.cursorrules](.cursorrules) : Directives strictes et conventions de code.
   - [config/agents_requirements.json](config/agents_requirements.json) : Exigences déclarées pour les agents.
   - [src/selector.py](src/selector.py) : Cœur logique pur de l'attribution.
2. **Exécuter la suite de tests pour vérifier l'intégrité :**
   ```bash
   python3 -m unittest discover tests
   ```
   *Tous les tests doivent être au vert.*
3. **Tester l'exécution principale :**
   ```bash
   python3 main.py --export
   ```

---

## 4. Composants & Responsabilités

| Module / Fichier | Responsabilité Principale | Contraintes Particulières |
|---|---|---|
| [`src/selector.py`](src/selector.py) | Filtrage, tri, sélection et surclassement | **Fonctions pures uniquement**. Aucun appel I/O, réseau ou HTTP. |
| [`src/fetcher.py`](src/fetcher.py) | Récupération OpenRouter & scoring heuristique | Backup puis écriture atomique ; rétention des sauvegardes horodatées. |
| [`src/budget.py`](src/budget.py) | Calcul des coûts au token & alertes de quotas | Seuil critique free-tier : `1_000_000` tokens/mois. |
| [`src/exporter.py`](src/exporter.py) | Génération pure du JSON pour OpenCode | **Fonctions pures uniquement**. Aucun appel I/O. Schéma officiel OpenCode strict (`opencode.json`) + rapport d'audit (`modelpool-report.json`). |
| [`src/service.py`](src/service.py) | Chargement, orchestration, export et sync | Seule couche I/O ; verrou pour les écritures concurrentes (`.modelpool.lock`). |
| [`src/web.py`](src/web.py) | Interface HTTP locale | Bind `127.0.0.1` uniquement ; stdlib ; protections CSRF/Origin ; pas de logique métier. |
| [`main.py`](main.py) | Interface CLI en ligne de commande | Supporte `--sync`, `--export [path]`, `--no-fallback`, `--serve [port]`, `--refresh-access`. |
| [`src/providers/router.py`](src/providers/router.py) | Priorisation et routage des canaux d'exécution (Ollama, Direct, OpenRouter) | Fonctions pures de routage selon la disponibilité des clés et modèles validés. |
| [`src/providers/detector.py`](src/providers/detector.py) | Détection sécurisée des identifiants et clés API | Inspection ordonnée (variables d'environnement, `.env`, auth OpenCode). |
| [`src/providers/access.py`](src/providers/access.py) | Sondage dynamique des modèles accessibles par clé API | Découverte en direct avec gestion de cache (`data/provider_access.json`). |
| [`src/providers/direct.py`](src/providers/direct.py) | Catalogues et spécifications des fournisseurs directs | Définitions statiques des modèles (Google, Mistral, Groq, Cerebras, Anthropic). |
| [`src/providers/ollama.py`](src/providers/ollama.py) | Détection et interrogation du service local Ollama | Découverte locale sur port 11434 sans dépendance tierce. |

---

## 5. État Actuel du Projet & Historique des Jalons

- ✅ **Jalon 1 (MVP) :** Structures `Model` et `AgentRequirement`, filtrage des outils et complexité, priorisation du gratuit.
- ✅ **Jalon 2 (Catalogue & Fallback) :** Intégration de modèles légers (scores 1-2), logique de surclassement (`fallback`) et tests de compatibilité.
- ✅ **Jalon 3 (Sync OpenRouter & Backups) :** Téléchargement dynamique via l'API OpenRouter, filtrage des tarifs négatifs, backups horodatés dans `data/backups/`.
- ✅ **Jalon 4 (Export OpenCode) :** Module d'export standardisé générant `config/opencode.json` et `config/modelpool-report.json` (initialement nommé `modelscope-report.json`).
- ✅ **Jalon 5 (Filtres Avancés) :** `min_context_window`, `allowed_providers`, `excluded_providers`, `force_model`.
- ✅ **Jalon 6 (Simulation Budgétaire) :** Calculs de coût mensuel au token, alertes de quotas free-tier, gestion du `max_monthly_budget`.
- ✅ **Jalon 7 (Interface web locale) :** Service applicatif partagé, serveur `127.0.0.1`, page unique de consultation.
- ✅ **Jalon 8 (Conformité & Durcissement) :** Schéma officiel OpenCode strict (additionalProperties: false), scoring de complexité par jetons délimités, sécurité CSRF/Origin et écritures atomiques.
- ✅ **Jalon 9 (Audit Phase 1 - Intégrité Économique & Durcissement Sécurité) :** Correction du tri `lowest_cost` avec primauté stricte du coût financier et départage déterministe (`model.id`), rejet des tarifs `null` et non finis (`NaN`/`Inf`), protection DNS Rebinding (`Host` check global) et en-têtes de sécurité HTTP (`CSP`, `X-Frame-Options`, `X-Content-Type-Options`), conformité stricte `"tool_call"` dans `Ressources/opencode.json(c)` et réactivation des assertions du test d'export corrompu.
- ✅ **Jalon 10 (Audit Phase 2 - Résilience, Concurrence & Durcissement) :** Réessai automatique avec backoff exponentiel et respect de `Retry-After` sur l'API OpenRouter (codes 429/5xx), verrou de fichier inter-processus POSIX via `fcntl.flock` dans `ApplicationService`, préservation des préfixes multi-fournisseurs (ex: `ollama/`) dans `format_opencode_model_id`, durcissement XSS avec échappement de l'apostrophe et écouteurs d'événements DOM non interpolés dans `web/index.html`, et couverture de test étendue sur les routes web (`/api/recalculate`, `/api/agent/update`, 404).
- ✅ **Jalon 11 (Audit Phase 3 - Architecture Pure & Accélération des Tests) :** Transformation de `src/exporter.py` en module de transformation pure (sans I/O ni dépendance système), rapatriement des écritures disque et backups dans `ApplicationService.export_config()` (`src/service.py`), coordination de terminaison du thread serveur de test par `threading.Event`, et accélération drastique de la suite de tests complète de 3.7s à ~0.16s.
- ✅ **Jalon 12 (Audit Phase 4 - Élimination Head-of-Line Blocking, Chaînage CLI & Unification Coût) :** Téléchargement réseau OpenRouter hors verrou (`MOD-04`), chaînage séquentiel de `--validate` et `--export` dans `main.py` (`MOD-06`), mise à jour documentaire de l'interface interactive dans `README.md` (`MOD-08`), et unification arithmétique canonique du calcul de coût dans `Model.calculate_cost` (`MOD-09`).
- ✅ **Jalon 13 (Audit Phase 5 - Finitions & Hygiène) :** Rétablissement des permissions de lecture standard `0o644` lors de l'écriture atomique (`MIN-01`), support du mode `"all"` dans `AgentRequirement.from_dict` (`MIN-03`), validation stricte de la plage de port `1-65535` sur `--serve` (`MIN-05`), arrêt propre sans traceback sur `KeyboardInterrupt` (`MIN-06`), et masquage des chemins absolus locaux dans les retours d'erreurs HTTP de l'API web (`MIN-07`).
- ✅ **Jalon 14 (Audit Phase 6 - Portabilité Windows, Scoring MoE & Fraîcheur Catalogue) :** Support du verrouillage inter-processus sous Windows natif via `msvcrt.locking` en complément de `fcntl.flock` POSIX (`src/service.py`), extraction et prise en compte de la masse de paramètres totale cumulée ($N \times M$) pour les architectures MoE (`NxMb`) dans `estimate_complexity_score` (`src/fetcher.py`), détection et avertissement de fraîcheur du catalogue (> 14 jours) intégrés dans `diagnostics` et relayés par le CLI (`main.py`) et l'interface Web (`web/index.html`).
- ✅ **Jalon 15 (Alignement Natif OpenCode & Liaison Directe) :** Alignement de `config/agents_requirements.json` sur le quatuor natif OpenCode (`build`, `plan`, `explore`, `general`), attribution automatique des modes primaires (`build`, `plan`) et sous-agents (`explore`, `general`) dans `src/exporter.py`, support de la résolution du tilde (`~`) dans `ApplicationService.resolve_export_path` pour cibler directement `~/.config/opencode/opencode.json`, et enrichissement documentaire de la liaison OpenCode-ModelPool-OpenCode dans `README.md`.
- ✅ **Jalon 16 (Multi-Fournisseurs & Priorité Canaux) :** Intégration hybride d'Ollama local (`:11434`), de 5 fournisseurs directs (Google AI Studio, Mistral, Groq, Cerebras, Anthropic) et d'OpenRouter ; détection automatique sécurisée des clés d'environnement et d'authentification OpenCode ; routage configurable par canal prioritaire (`--provider-priority`) avec repli OpenRouter ; interface Web avec panneau de réordonnancement drag-and-drop.
- ✅ **Jalon 17 (Vérification Dynamique des Modèles par Clé API) :** Sondage en direct des endpoints des fournisseurs pour vérifier les modèles réellement activés par clé (`src/providers/access.py`) ; cache persistant `data/provider_access.json` ; routage conditionnel strict au canal direct uniquement si le modèle est validé ; CLI `--refresh-access` et bouton Web "Vérifier clés".
- ✅ **Jalon 18 (Renommage OpenCode-ModelPool) :** Renommage institutionnel et technique du projet de ModelScope vers OpenCode-ModelPool : configuration (`pyproject.toml`), scripts lanceurs, documentation, modèle d'export (`build_modelpool_report_data` avec alias de rétrocompatibilité), verrou inter-processus (`.modelpool.lock`) et rapport d'audit (`config/modelpool-report.json`).
- ✅ **Jalon 19 (Priorité des canaux, Export routé & Chaînes de repli) :** la priorité des fournisseurs oriente désormais la *sélection* (`channel_rank` pur dans `src/selector.py`, rang du canal prioritaire avant tout autre critère), l'export `opencode.json` utilise l'identifiant du canal retenu (ex: `mistral/...`), `fallback_chain` par agent dans `modelpool-report.json` (compatible plugins OpenCode de repli sur 429 comme `@azumag/opencode-rate-limit-fallback`), et correction du sondage Groq/Cerebras (User-Agent bloqué par Cloudflare erreur 1010).
- ✅ **Jalon 20 (Finalisation V0.2 - Audit Indépendant MP-201 à MP-218) :**
  - **M1 (Intégrité & Rôles)** : Préservation stricte de la configuration racine (`provider_priority`, clés personnalisées) lors des updates agents ; commandes de synchronisation explicites (`--sync-openrouter` vs `--sync-all`) ; élimination des faux "prêt" (OpenRouter gratuit requiert des identifiants valides) ; permissions OpenCode différenciées (`plan`/`explore` en `edit: deny`, `build` en `edit: allow`).
  - **M2 (Routage & Sécurité d'Export)** : Métadonnées explicites d'offre sur `ExecutionTarget` ; validation du schéma OpenCode préalable à l'écriture disque, prévisualisation unifiée (`--diff`/`--preview`) et restauration d'urgence (`--rollback`) ; contrôle strict d'exécutabilité (`--check-ready`) ; réconciliation des stratégies de tri (`lowest_cost` financier strict vs `prefer_provider`).
  - **M3 (Fiabilisation Budgétaire, Cache & Sécurité)** : Distinction des sources de prix réelles, affichage "Non estimable" sans coût répertorié, disclaimers locaux 0$, avertissements de quota prévisionnels ; horodatage et TTL de cache (`max_cache_age_days = 14`), classification des erreurs HTTP et auth sécurisée Google (`x-goog-api-key`) ; durcissement HTTP Web (vérification stricte du schéma/port Origin, rejet des traversées de répertoires `..`).
  - **M4 & M5 (UX, Validation & Release)** : Interface Web interactive enrichie (panneau de diff unifié, boutons d'action séparés) ; protocoles de validation E2E (`docs/validation-opencode-v0.2.md`) et de benchmark comparatif (`docs/evaluations/comparative_benchmark_v0.2.md`) ; mise à jour `README.md` et `CHANGELOG.md` pour la release v0.2.0.
---

## 6. Prochaines Étapes Recommandées (Roadmap)

Si le projet doit continuer d'évoluer, les tâches prioritaires suivantes sont identifiées :
1. ✅ **Gestion multi-sources (Complété) :** Agrégation d'Ollama local et des 5 fournisseurs directs (Google, Mistral, Groq, Cerebras, Anthropic) avec routage automatique et priorité des canaux.
2. **Automatisation de la veille de modèles :** Cron GitHub Actions (ou tâche planifiée) pour mettre à jour `data/models.json` chaque semaine depuis OpenRouter.
3. **Fiabilisation du catalogue & exclusion des modèles non-LLM :** Filtrage automatique strict des modèles audio/musique (Lyria, etc.), TTS, transcription, embeddings purs et robotique pour empêcher toute attribution non pertinente aux agents de code.
4. ✅ **Intégration & délégation outillée Google AI Pro (Complété) :** Formalisation des protocoles et points de contact spécifiques pour déléguer les benchmarks de pricing à Gemini Deep Research, la veille documentaire à NotebookLM et la validation CI/CD à Jules (voir section 8).
5. **Pénalité de fiabilité free-tier :** Pondération ou option de désactivation des modèles `:free` pour les agents critiques.

---

## 7. Règle d'Or pour Chaque Intervention

> **Ne proposez jamais de commit sans avoir créé ou mis à jour les tests unitaires correspondants dans `tests/` et sans avoir vérifié que `python3 -m unittest discover tests` s'exécute avec succès.**

---

## 8. Intégration & Délégation Google AI Pro 🚀

Le projet formalise ses protocoles et points de contact avec l'écosystème d'outils avancés **Google AI Pro** sous [`docs/google_ai_pro/`](docs/google_ai_pro/) afin d'enrichir ses capacités d'intelligence sans alourdir le runtime Python :

### 1. Gemini Deep Research (`docs/google_ai_pro/deep_research/`)
- **Rôle** : Exploration autonome du marché des LLMs, benchmarks de tarification multi-fournisseurs ($/1M tokens) et surveillance des quotas/rate-limits.
- **Points de contact** :
  - [`prompts/pricing_benchmark.md`](docs/google_ai_pro/deep_research/prompts/pricing_benchmark.md) : Benchmark tarifaire multi-fournisseurs (LLMs code/texte uniquement, exclusion des modèles audio/multimédia purs).
  - [`prompts/provider_updates.md`](docs/google_ai_pro/deep_research/prompts/provider_updates.md) : Veille des versions d'API, endpoints et dépréciations.
  - [`prompts/token_monitoring.md`](docs/google_ai_pro/deep_research/prompts/token_monitoring.md) : Surveillance des quotas free-tier (RPM/TPM/RPD) et calibrage des alertes `src/budget.py`.
  - [`schemas/benchmark_output.schema.json`](docs/google_ai_pro/deep_research/schemas/benchmark_output.schema.json) : Schéma de validation JSON conforme au contrat `src/selector.py:Model`.
  - [`workflows/ingestion_procedure.md`](docs/google_ai_pro/deep_research/workflows/ingestion_procedure.md) : Procédure pas-à-pas de validation et fusion atomique dans `data/models.json`.

### 2. NotebookLM (`docs/google_ai_pro/notebooklm/`)
- **Rôle** : Mémoire architecturale continue sans hallucination (grounding exclusif sur le dépôt), analyse d'impact des évolutions et radar des nouvelles parutions.
- **Points de contact** :
  - [`source_ingestion_guide.md`](docs/google_ai_pro/notebooklm/source_ingestion_guide.md) : Guide d'ingestion et découpage en faisceaux documentaires (limite 500k mots).
  - [`sources/curated_sources.json`](docs/google_ai_pro/notebooklm/sources/curated_sources.json) : Répertoire des sources internes et flux officiels des fournisseurs.
  - [`prompts/architecture_grounding.md`](docs/google_ai_pro/notebooklm/prompts/architecture_grounding.md) : Requêtes d'analyse d'invariants et d'impact architectural.
  - [`prompts/model_release_eval.md`](docs/google_ai_pro/notebooklm/prompts/model_release_eval.md) : Grille d'évaluation des nouveaux modèles pour les agents `build`, `plan`, `explore`, `general`.
  - [`prompts/audio_overview_brief.md`](docs/google_ai_pro/notebooklm/prompts/audio_overview_brief.md) : Canevas de podcast technique 2 voix (Audio Overview).

### 3. Jules - Google Labs Coding Agent (`docs/google_ai_pro/jules/` & `.jules/`)
- **Rôle** : Agent de codage autonome opérant dans des VMs cloud GitHub pour la relecture de PR, la reproduction de bogues et l'implémentation de correctifs auto-validés.
- **Points de contact** :
  - [`.jules/instructions.md`](.jules/instructions.md) : Fichier ancrage à la racine pour prise en compte immédiate par Jules.
  - [`.github/workflows/jules-validation.yml`](.github/workflows/jules-validation.yml) : Workflow CI/CD déclenché sur les PRs ou commentaires étiquetés `jules`.
  - [`prompts/pr_review_prompt.md`](docs/google_ai_pro/jules/prompts/pr_review_prompt.md) : Grille d'évaluation automatisée de PR.
  - [`prompts/bugfix_workflow.md`](docs/google_ai_pro/jules/prompts/bugfix_workflow.md) : Protocole TDD autonome de reproduction et résolution de bogues.
