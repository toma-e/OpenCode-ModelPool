# ModelScope 🎯

> **Attribution automatique et optimisation de modèles LLM pour les agents OpenCode.**

ModelScope analyse dynamiquement un catalogue de modèles LLM (tarifs, fenêtres de contexte, quotas gratuits, support des outils) et sélectionne la configuration optimale pour chaque agent de votre parc, selon son niveau d'exigence et son budget.

---

## 💡 Pourquoi ModelScope ?

Dans un écosystème multi-agents (comme **OpenCode**), affecter systématiquement un modèle coûteux (ex: Claude 3.5 Sonnet, GPT-5) à tous les agents est inefficace :
- Un agent de documentation (`doc_agent`) n'a besoin que d'un modèle simple, rapide et si possible gratuit.
- Un agent de refactoring (`coder_agent`) a besoin d'outils (`tools`) et d'une complexité intermédiaire.
- Seul un agent de conception ou de débogage avancé (`architect_agent`) justifie un modèle de pointe.

ModelScope automatise ce routage intelligent, simule votre budget prévisionnel et génère directement le fichier de configuration exploitable par OpenCode.

---

## 🏗️ Architecture du Projet

Le projet est conçu en Python 3.11+ avec la bibliothèque standard (zéro dépendance externe pour l'exécution principale) :

```text
modelscope/
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

1. **Catalogue Dynamique & API OpenRouter :**
   - Synchronisation en direct depuis l'endpoint public d'OpenRouter sans clé d'API obligatoire.
   - Déduction automatique des scores de complexité (1 à 5), support des outils et calcul des tarifs par million de tokens.
   - Système de **backup horodaté automatique** avant chaque mise à jour.

2. **Moteur de Sélection Typé & Intelligent :**
   - Filtrage strict : niveau de complexité (`min_complexity`, `max_complexity`), support des outils (`requires_tools`), fenêtre de contexte minimale (`min_context_window`).
   - Listes blanches et noires de fournisseurs (`allowed_providers`, `excluded_providers`).
   - Forçage manuel possible (`force_model`). Il reste volontairement prioritaire sur
     toutes les contraintes ; l'attribution et l'export indiquent explicitement les
     contraintes techniques ou budgétaires ainsi contournées.
   - Priorisation absolue du niveau gratuit (`prefer_free = true`).
   - **Surclassement économique automatique (`fallback`) :** si aucun modèle n'est disponible dans la plage exacte, surclassement vers le modèle compatible le plus économique.

3. **Simulation Budgétaire & Quotas :**
   - Calcul des coûts mensuels par agent en fonction du volume estimé de tokens d'entrée/sortie.
   - Alertes en cas de dépassement du plafond budgétaire (`max_monthly_budget`).
   - Détection des risques de limitation de débit (`rate-limit / RPM / TPM`) sur les modèles gratuits à fort volume.
   - Estimation des économies financières réalisées grâce aux modèles gratuits.

4. **Export OpenCode Standardisé :**
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
# Ou vers un chemin personnalisé :
python3 main.py --export /chemin/vers/opencode.json
```

### Forcer la Synchronisation depuis OpenRouter
Pour télécharger les derniers modèles disponibles tout en archivant l'ancienne version :
```bash
python3 main.py --sync
# Ou directement via le module fetcher :
python3 -m src.fetcher
```

### Interface Web Locale
Pour consulter les affectations dans le navigateur (écoute uniquement sur `127.0.0.1`) :
```bash
python3 main.py --serve
# Port personnalisé :
python3 main.py --serve 9000
```
Ouvrir ensuite `http://127.0.0.1:8765/`. Les exigences d'agents restent en lecture seule.

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
| `--sync` | Télécharge et met à jour le catalogue depuis OpenRouter avec création d'un backup. |
| `--no-fallback` | Désactive le surclassement automatique si aucun modèle exact n'est trouvé. |
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

## 🤝 Collaboration Multi-Agents

Ce projet est conçu pour être développé et maintenu par plusieurs agents de code en parallèle :
- **Cursor / Windsurf :** pilotés via [`.cursorrules`](.cursorrules)
- **Claude Code (Anthropic) :** piloté via [`CLAUDE.md`](CLAUDE.md)
- **GitHub Copilot / OpenAI Codex :** piloté via [`.github/copilot-instructions.md`](.github/copilot-instructions.md)
- **Mistral AI / Codestral :** piloté via [`MISTRAL.md`](MISTRAL.md)
- **OpenCode, Antigravity, Aider & autres :** pilotés via [`AGENTS.md`](AGENTS.md)

Consultez [AGENTS.md](AGENTS.md) pour la documentation complète d'onboarding, les invariants et l'architecture.
