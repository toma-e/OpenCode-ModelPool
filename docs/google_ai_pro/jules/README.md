# Jules (Google Labs Coding Agent) : Guide de Configuration & Délégation 🤖

## 1. Présentation de Jules

**Jules** est un agent de développement logiciel autonome développé par **Google Labs**. Il s'intègre nativement à GitHub pour exécuter des cycles complets de maintenance logicielle à l'intérieur d'environnements cloud sécurisés (Cloud VMs).

### Caractéristiques Majeures :
- **Détection Native des Invariants** : Jules inspecte automatiquement la racine du dépôt GitHub et obéit en priorité à [`AGENTS.md`](../../../AGENTS.md) et [`.jules/instructions.md`](../../../.jules/instructions.md).
- **Cycle Autonome** : Prise en charge d'un ticket (Issue), reproduction par un test unitaire rouge, implémentation minimale du correctif, passage de la suite de tests au vert, et soumission d'une Pull Request documentée.
- **Validation CI/CD Dédiée** : Chaque proposition de Jules déclenche le workflow de vérification automatisé [`.github/workflows/jules-validation.yml`](../../../.github/workflows/jules-validation.yml).

---

## 2. Invariants Non-Négociables pour Jules

Lorsqu'il intervient sur OpenCode-ModelPool, Jules est soumis à quatre règles absolues :
1. **Modules Purs Sans Effets de Bord** :
   - `src/selector.py` et `src/exporter.py` DOIVENT rester des fonctions 100% pures (aucun appel `open()`, aucun import réseau `urllib`, aucune dépendance temporelle/aléatoire).
   - Toutes les entrées/sorties et accès disque doivent être confinés dans `src/service.py` ou `src/fetcher.py`.
2. **Zéro Dépendance Externe au Runtime** :
   - L'exécution principale (`main.py`, `src/`) s'appuie UNIQUEMENT sur la bibliothèque standard Python (`stdlib`).
   - Aucune dépendance tierce (ex: `requests`, `pydantic`) ne doit être ajoutée aux dépendances de production.
3. **Discipline de Test Rigoureuse** :
   - Toute modification ou correction de bug DOIT comporter son test unitaire associé dans `tests/test_*.py`.
   - La suite `python3 -m unittest discover tests` et la commande `python3 main.py --validate` doivent s'exécuter avec succès avant l'ouverture de la PR.
4. **Vérification Statique** :
   - Le code produit doit satisfaire `ruff check .` et `mypy .`.

---

## 3. Protocoles et Prompts Disponibles

| Document | Rôle |
|---|---|
| [`jules_instructions.md`](jules_instructions.md) | Consignes complètes destinées au moteur d'exécution de Jules en machine virtuelle |
| [`prompts/pr_review_prompt.md`](prompts/pr_review_prompt.md) | Grille d'évaluation et prompt de relecture automatisée de Pull Request |
| [`prompts/bugfix_workflow.md`](prompts/bugfix_workflow.md) | Protocole standardisé de reproduction de bogue et création de PR corrective |
| [`.jules/instructions.md`](../../../.jules/instructions.md) | Fichier ancrage à la racine du dépôt pour prise en charge automatique par Jules |
| [`.github/workflows/jules-validation.yml`](../../../.github/workflows/jules-validation.yml) | Workflow GitHub Actions déclenché sur les PRs ou commentaires étiquetés `jules` |

---

## 4. Modalités de Déclenchement sur GitHub

Pour déléguer une tâche à Jules :
1. **Via GitHub Issues** :
   - Créez une issue décrivant le comportement attendu ou l'anomalie constatée.
   - Ajoutez le label `jules`.
   - Jules provisionne une VM cloud, checkout la branche principale, reproduit le problème, résout le ticket et soumet une PR liée.
2. **Via Commentaire sur PR ou Issue** :
   - Tapez `/jules review` pour déclencher une revue de code automatisée selon la grille [`prompts/pr_review_prompt.md`](prompts/pr_review_prompt.md).
   - Tapez `/jules fix <description>` pour demander une correction ciblée.
