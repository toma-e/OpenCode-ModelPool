# OpenCode-ModelPool 🎯

> **Attribution automatique et optimisation de modèles LLM pour les agents OpenCode.**

OpenCode-ModelPool analyse dynamiquement un catalogue de modèles LLM (tarifs, fenêtres de contexte, quotas gratuits, support des outils) et sélectionne la configuration optimale pour chaque agent de votre parc, selon son niveau d'exigence et son budget.

---

## 💡 Pourquoi OpenCode-ModelPool ?

Dans un écosystème multi-agents (comme **OpenCode**), affecter systématiquement un modèle coûteux (ex: Claude 3.5 Sonnet, GPT-5) à tous les agents est inefficace :
- **`build`** (agent principal de codage) requiert un support d'outils complet (`tools`), un fort raisonnement et une génération de code précise.
- **`plan`** (agent principal d'architecture et de cadrage) requiert une très grande fenêtre de contexte, de la vision et du raisonnement de pointe, sans nécessiter d'outils d'écriture directe.
- **`explore`** (sous-agent de recherche rapide) n'a besoin que d'un modèle simple, très rapide, en lecture seule et si possible gratuit.
- **`general`** (sous-agent polyvalent) traite les tâches déléguées avec un compromis équilibré coût/performance.

OpenCode-ModelPool automatise ce routage intelligent, simule votre budget prévisionnel et génère directement le fichier de configuration exploitable par OpenCode.

---

## 🏗️ Architecture du Projet

Le projet est conçu en Python 3.11+ avec la bibliothèque standard (zéro dépendance externe pour l'exécution principale) :

```text
opencode-modelpool/
├── config/
│   ├── agents_requirements.json   # Définition des besoins des agents (complexité, outils, budget...)
│   └── opencode.json              # Configuration cible générée pour OpenCode
├── data/
│   ├── models.json                # Catalogue actif des modèles LLM (tarifs, capacités, scores)
│   ├── models.json.bak            # Copie de sauvegarde immédiate
│   └── backups/                   # Historique horodaté des catalogues précédents
├── src/
│   ├── selector.py                # Moteur d'attribution, filtrage strict & surclassement (fallback)
│   ├── fetcher.py                 # Synchronisation dynamique via l'API OpenRouter & backups
│   ├── budget.py                  # Simulation des coûts mensuels, quotas & alertes rate-limits
│   ├── exporter.py                # Génération du format de configuration OpenCode
│   ├── service.py                 # Orchestration (fichiers, sélection, export, sync)
│   └── web.py                     # Serveur HTTP local 127.0.0.1
├── web/
│   └── index.html                 # Interface unique (affectations, budget, actions)
├── tests/
│   ├── test_selector.py           # Tests du sélecteur et des filtres avancés
│   ├── test_fetcher.py            # Tests du parsing OpenRouter et de la sauvegarde
│   ├── test_budget.py             # Tests du calcul des coûts et alertes quotas
│   ├── test_exporter.py           # Tests de la structure d'export OpenCode
│   ├── test_service.py            # Tests du service applicatif
│   └── test_web.py                # Tests des routes HTTP locales
├── main.py                        # Interface CLI principale
├── .cursorrules                   # Règles de développement pour agents IA (Cursor, Windsurf...)
├── AGENTS.md                      # Guide universel pour les agents de code
└── README.md                      # Documentation du projet
```

---

## ⚙️ Fonctionnalités Clés

1. **Catalogue Multi-Fournisseurs & Modèles Locaux :**
   - Synchronisation hybride : endpoint public OpenRouter, interrogation locale d'**Ollama** (`http://localhost:11434`), et APIs directes (Google AI Studio, Mistral, Groq, Cerebras, Anthropic).
   - Déduction automatique des scores de complexité (1 à 5), support des outils et calcul des tarifs par million de tokens.
   - Système de **backup horodaté automatique** avant chaque mise à jour.

2. **Détection des Clés & Vérification d'Accès Réel :**
   - Détection automatique sécurisée des clés configurées dans l'environnement (`os.environ`, `.env`, ou `~/.local/share/opencode/auth.json`).
   - **Vérification dynamique des modèles accessibles** (`--refresh-access`) : interroge directement les endpoints des fournisseurs (ex: Google `v1beta/models`) pour vérifier quels modèles sont réellement exploitables avec chaque clé.
   - Filtrage du vivier d'attribution par clés actives (`--filter-keys`).

3. **Routage d'Exécution & Priorité des Canaux :**
   - Format d'export OpenCode intelligent : modèle local direct (`ollama/<id>`), direct provider (`<provider>/<id>`), ou proxy OpenRouter (`openrouter/<id>`).
   - Priorité configurable de routage (`--provider-priority "ollama,google,mistralai,openrouter"`), réorganisable aussi par glisser-déposer dans l'interface Web.
   - Fallback automatique vers OpenRouter si une clé directe n'a pas accès à un modèle donné.

4. **Moteur de Sélection Typé & Intelligent :**
   - Filtrage strict : niveau de complexité (`min_complexity`, `max_complexity`), support des outils (`requires_tools`), fenêtre de contexte minimale (`min_context_window`).
   - Listes blanches et noires de fournisseurs (`allowed_providers`, `excluded_providers`).
   - Forçage manuel possible (`force_model`). Il reste volontairement prioritaire sur
     toutes les contraintes ; l'attribution et l'export indiquent explicitement les
     contraintes techniques ou budgétaires ainsi contournées.
   - Priorisation absolue du niveau gratuit (`prefer_free = true`).
   - **Surclassement économique automatique (`fallback`) :** si aucun modèle n'est disponible dans la plage exacte, surclassement vers le modèle compatible le plus économique.

5. **Simulation Budgétaire & Quotas :**
   - Calcul des coûts mensuels par agent en fonction du volume estimé de tokens d'entrée/sortie.
   - Alertes en cas de dépassement du plafond budgétaire (`max_monthly_budget`).
   - Détection des risques de limitation de débit (`rate-limit / RPM / TPM`) sur les modèles gratuits à fort volume.
   - Estimation des économies financières réalisées grâce aux modèles gratuits.

6. **Export OpenCode Standardisé :**
   - Génère un fichier `config/opencode.json` prêt à être injecté dans les agents OpenCode.

---

## 🚀 Démarrage Rapide

### Prérequis
- Python 3.11 ou supérieur.

### Exécution Simple
Pour exécuter l'attribution automatique avec le catalogue existant :
```bash
python3 main.py
```

### Exécution avec Export OpenCode
Pour attribuer les modèles et exporter la configuration pour OpenCode :
```bash
python3 main.py --export
```

#### 🔗 Liaison avec votre environnement OpenCode

OpenCode recherche sa configuration à deux emplacements standards :
1. **Au niveau utilisateur (global) :** `~/.config/opencode/opencode.json`
2. **Au niveau d'un projet spécifique :** `.opencode/opencode.json` ou `opencode.json` à la racine de votre projet.

Vous pouvez lier OpenCode-ModelPool à OpenCode de trois manières :

- **Option 1 : Export direct dans la configuration globale d'OpenCode**
  ```bash
  python3 main.py --export ~/.config/opencode/opencode.json
  ```
- **Option 2 : Export direct dans le projet de votre choix**
  ```bash
  python3 main.py --export /chemin/vers/mon-projet/.opencode/opencode.json
  ```
- **Option 3 : Liaison automatique via lien symbolique (Symlink)**
  Conservez l'export dans `config/opencode.json` de OpenCode-ModelPool et créez un lien symbolique :
  ```bash
  mkdir -p ~/.config/opencode
  ln -sf "$(pwd)/config/opencode.json" ~/.config/opencode/opencode.json
  ```
  *(Chaque ré-export ou mise à jour via l'interface web sera immédiatement pris en compte par OpenCode).*


### Forcer la Synchronisation depuis OpenRouter
Pour télécharger les derniers modèles disponibles tout en archivant l'ancienne version :
```bash
python3 main.py --sync
# Ou directement via le module fetcher :
python3 -m src.fetcher
```

### Intégration Rapide de Benchmarks Gemini Deep Research
Pour intégrer de nouveaux tarifs ou modèles sourcés via Deep Research de manière interactive :
```bash
python3 import-deep-research.py
# Ou directement en ligne de commande :
python3 main.py --import-models chemin/vers/resultats.json
```

### Interface Web Locale
Pour consulter les affectations dans le navigateur (écoute uniquement sur `127.0.0.1`) :
```bash
python3 main.py --serve
# Port personnalisé :
python3 main.py --serve 9000
```
Ouvrir ensuite `http://127.0.0.1:8765/`. L'interface permet de visualiser le catalogue, les attributions d'agents, les simulations budgétaires, et de modifier interactivement les exigences de chaque agent (stratégie, gratuit/payant, vision, raisonnement, tier 1) avec persistance atomique.

#### Lanceurs Windows (via WSL)
Si votre projet est dans WSL et vous utilisez Windows, des lanceurs sont disponibles :

**Démarrage :**
- PowerShell : ./start-web.ps1 (recommandé)
- Batch : start-web.bat

**Arrêt :**
- PowerShell : ./stop-web.ps1 (recommandé)
- Batch : stop-web.bat

Ces scripts lancent automatiquement le serveur dans WSL et ouvrent le navigateur Windows.
Consultez LANCEURS.md pour plus de détails.

### Options en Ligne de Commande

| Option | Description |
|---|---|
| `--export [PATH]` | Génère le fichier de configuration OpenCode (défaut : `config/opencode.json`). |
| `--validate` | Valide la compatibilité de tous les agents (code de sortie 1 si au moins un agent reste sans modèle). Enchaînable avec `--export`. |
| `--sync` | Télécharge et met à jour le catalogue multi-fournisseurs (OpenRouter, Ollama, APIs directes) avec backup. |
| `--status-keys` | Affiche l'état des clés API détectées et le nombre de modèles vérifiés par fournisseur. |
| `--refresh-access` | Interroge les APIs directes (Google, Mistral, Groq...) pour vérifier les modèles réellement accessibles par clé. |
| `--filter-keys` | Ne retient dans le vivier d'attribution que les modèles rattachés à des clés disponibles ou locaux/gratuits. |
| `--provider-priority LIST` | Définit l'ordre de priorité des canaux d'exécution séparés par des virgules (ex: `ollama,google,mistralai,openrouter`). |
| `--no-ollama` | Désactive l'interrogation d'Ollama local lors de la synchronisation. |
| `--no-fallback` | Désactive le surclassement automatique si aucun modèle exact n'est trouvé. |
| `--models PATH` | Spécifie un chemin personnalisé vers `models.json`. |
| `--agents PATH` | Spécifie un chemin personnalisé vers `agents_requirements.json`. |
| `--serve [PORT]` | Démarre l'interface web locale sur 127.0.0.1 (défaut : 8765). |
| `-h`, `--help` | Affiche l'aide détaillée. |

---

## 🧪 Tests Unitaires

Le projet dispose d'une suite de tests complète sans dépendance externe :

```bash
python3 -m unittest discover tests
```

Pour les contrôles statiques (après installation des dépendances de développement) :

```bash
python3 -m ruff check .
python3 -m mypy .
```

La CI GitHub Actions exécute ces trois contrôles sous Python 3.11 et 3.12 à chaque
push et pull request.

---

## 🤝 Collaboration Multi-Agents & Écosystème Google AI Pro

Ce projet est conçu pour être développé et maintenu par plusieurs agents de code en parallèle :
- **Cursor / Windsurf :** pilotés via [`.cursorrules`](.cursorrules)
- **Claude Code (Anthropic) :** piloté via [`CLAUDE.md`](CLAUDE.md)
- **GitHub Copilot / OpenAI Codex :** piloté via [`.github/copilot-instructions.md`](.github/copilot-instructions.md)
- **Mistral AI / Codestral :** piloté via [`MISTRAL.md`](MISTRAL.md)
- **OpenCode, Antigravity, Aider & autres :** pilotés via [`AGENTS.md`](AGENTS.md)
- **Jules (Google Labs) :** agent de codage autonome en cloud VM piloté via [`.jules/instructions.md`](.jules/instructions.md) et validé automatiquement par CI/CD ([`.github/workflows/jules-validation.yml`](.github/workflows/jules-validation.yml)).

### 🚀 Délégation Avancée Google AI Pro
Pour enrichir ses capacités d'intelligence de marché sans alourdir le runtime Python standard :
- **Gemini Deep Research :** benchmarks tarifaires multi-fournisseurs et surveillance des quotas ([`docs/google_ai_pro/deep_research/`](docs/google_ai_pro/deep_research/)).
- **NotebookLM :** mémoire architecturale continue sans hallucination et radar de modèles ([`docs/google_ai_pro/notebooklm/`](docs/google_ai_pro/notebooklm/)).
- **Jules (Google Labs) :** automatisation de la relecture de PR et résolution de bogues ([`docs/google_ai_pro/jules/`](docs/google_ai_pro/jules/)).

Consultez [AGENTS.md](AGENTS.md) pour la documentation complète d'onboarding, les invariants et l'architecture générale, ainsi que le dossier [`docs/google_ai_pro/`](docs/google_ai_pro/).
