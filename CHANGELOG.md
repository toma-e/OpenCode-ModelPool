# Journal des Modifications (CHANGELOG) 📝

Toutes les modifications notables apportées à ce projet sont documentées dans ce fichier.
Le format est basé sur [Keep a Changelog](https://keepachangelog.com/fr/1.0.0/), et ce projet adhère à [Semantic Versioning](https://semver.org/lang/fr/).

---

## [0.3.0] — 2026-10-30

### 🚀 Nouveautés & Fonctionnalités Majeures

- **Pénalité de Fiabilité Free-Tier & Mode Stabilité (`reliability_preference`)** :
  - Introduction du champ `reliability_preference` (`prefer_stability`, `balanced`, `prefer_free`) sur les exigences d'agents.
  - En mode `prefer_stability`, les modèles cloud gratuits saturés subissent un malus de classement, favorisant les modèles payants stables et les modèles locaux Ollama (0$ hors quota cloud).
  - Contrôles et sélecteurs dédiés dans l'interface Web locale (`web/index.html`).
- **Synchronisation Conditionnelle de Fraîcheur (`--sync-if-stale`)** :
  - Nouveau drapeau CLI `python3 main.py --sync-if-stale [DAYS]` (défaut : 14 jours) réactualisant automatiquement le catalogue si la date `last_updated` est dépassée.
- **Bibliothèque de Profils Types d'Agents (Presets)** :
  - Module pur [`src/presets.py`](src/presets.py) fournissant 5 profils prédéfinis prêts à l'emploi : `coder_heavy`, `code_reviewer`, `fast_researcher`, `doc_writer`, `test_runner`.
  - Commandes CLI `python3 main.py --list-presets` et `python3 main.py --add-preset <identifiant> [nom_agent]`.
  - Panneau d'ajout rapide d'agents par preset dans l'interface Web (`POST /api/agent/add-preset`).
- **Découplage Modulaire de l'Architecture (`src/diagnostics.py`)** :
  - Extraction des fonctions pures de diagnostic d'intégrité et de contrôle temporel de catalogue dans [`src/diagnostics.py`](src/diagnostics.py), allégeant substantiellement `ApplicationService`.
- **Résolution Normalisée des Tarifs Direct Providers** :
  - Fonction `get_known_model_pricing` dans `src/providers/direct.py` pour résoudre les identifiants sans préfixe `models/` (notamment Google Gemini et Cerebras Llama 3.1/3.3).

---

## [0.2.0] — 2026-10-19

### 🚀 Nouveautés & Fonctionnalités Majeures

- **Contrôle Strict d'Exécutabilité (`--check-ready`) [MP-203, MP-207]** :
  - Introduction d'un mode de vérification strict qui garantit que chaque modèle attribué dispose d'un canal d'exécution prouvé (clé d'API active et vérifiée auprès du fournisseur, ou service local Ollama actif).
  - Élimination des faux positifs : un modèle gratuit ou présent dans le catalogue n'est plus marqué "prêt" si ses identifiants sont manquants ou non validés.
- **Prévisualisation & Restauration d'Export (`--diff`, `--rollback`) [MP-206]** :
  - Drapeaux CLI `--diff` / `--preview` pour visualiser le diff unifié avant toute modification de configuration.
  - Drapeau CLI `--rollback` pour restaurer instantanément la version précédente depuis une sauvegarde horodatée (`data/backups/`) ou fichier `.bak`.
  - Validation stricte du schéma officiel OpenCode (`additionalProperties: false`) préalable à toute écriture disque.
- **Séparation Explicite des Synchronisations CLI & Web [MP-202, MP-214]** :
  - `--sync-openrouter` : téléchargement du catalogue public OpenRouter sans écraser les connecteurs locaux.
  - `--sync-all` : synchronisation multi-fournisseurs (OpenRouter, Ollama local, Google, Mistral, Groq, Cerebras, Anthropic).
  - Dans l'interface Web : boutons distincts « Sync OpenRouter » et « Sync Tous ».
- **Transparence Budgétaire & Tarifs Réels [MP-210, MP-211]** :
  - Prise en compte des tarifs spécifiques au canal retenu (prix direct vs OpenRouter vs local gratuit).
  - Affichage explicite « Non estimable » si un modèle payant ne possède pas de tarif connu, évitant l'affichage erroné d'un coût de 0.0000 $.
  - Disclaimers sur l'exécution locale (0$ API, hors infrastructure matérielle).
  - Avertissements de quota formulés comme seuils heuristiques prévisionnels (non-garantis contractuellement par l'API).
- **Gestion Avancée du Cache & Fraîcheur des Accès [MP-212]** :
  - Horodatage des sondages d'API avec durée de validité configurable (`max_cache_age_days = 14`).
  - En mode strict (`--check-ready`), un cache expiré est traité comme non vérifié.
  - Différenciation des erreurs HTTP : 401/403 (authentification refusée), 429 (débit limité temporaire), 404, indisponibilités réseau et timeouts.
  - Limitation de concurrence (`max_workers = 4`) pour prévenir les blocages de débit amont.
  - Authentification par en-tête `x-goog-api-key` pour Google AI Studio, éliminant tout risque de fuite de clé dans les URLs ou journaux.
- **Durcissement de Sécurité HTTP & Local [MP-215]** :
  - Vérification stricte de l'en-tête `Origin` (schéma HTTP obligatoire, validation du port d'écoute exact).
  - Protection contre le DNS Rebinding (`Host` whitelisté sur `127.0.0.1` et `localhost`).
  - Rejet systématique de la traversée de répertoires (`..`) et interdiction d'export hors du projet ou de `~/.config/opencode/`.
  - En-têtes défensifs `Content-Security-Policy`, `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`.
- **Rôles OpenCode & Permissions Différenciées [MP-205]** :
  - `plan` et `explore` : mode subagent ou primary avec `requires_tools: true` et interdiction stricte de modification de fichiers (`permission: {"edit": "deny"}`).
  - `build` : mode primary avec droits d'édition de code autorisés (`permission: {"edit": "allow"}`).

### 🛠️ Améliorations & Refactorisations

- **Stratégies de Tri Déterministes [MP-209]** :
  - `lowest_cost` : primauté absolue du coût financier calculé sur le canal d'exécution effectif.
  - `prefer_provider` : priorité donnée à l'ordre des canaux configuré avant le critère de coût.
- **Métadonnées d'Offre Enrichies [MP-204]** :
  - Structure `ExecutionTarget` enrichie avec `native_model_id`, `pricing_source`, `is_heuristic_match`, `verification_status`.
- **Préservation Intégrale de la Configuration Racine [MP-201]** :
  - L'édition d'un agent via le CLI ou le Web préserve strictement `provider_priority` et toutes les clés racine personnalisées de `config/agents_requirements.json`.
- **Prévisualisation Web Intégrée [MP-214]** :
  - Ajout de l'endpoint `/api/diff` et d'un panneau déroulant de prévisualisation du diff unifié dans l'interface Web locale.

### 🧪 Validation & Tests

- 169 tests unitaires automatisés s'exécutant en ~0.4s avec 100% de réussite (`python3 -m unittest discover tests`).
- Zéro dépendance réseau payante dans la suite de tests (usage exclusif de mocks et fixtures).
- Rédaction du protocole de validation OpenCode en conditions réelles (`docs/validation-opencode-v0.2.md`).
- Définition du banc d'essai comparatif de qualité et de coût (`docs/evaluations/comparative_benchmark_v0.2.md`).

---

## [0.1.0] — 2026-10-14

- Version initiale d'OpenCode-ModelPool (MVP).
- Filtrage par complexité, taille de contexte et outils.
- Support du surclassement économique (`fallback`).
- Connexion initiale au catalogue OpenRouter et détection locale Ollama.
