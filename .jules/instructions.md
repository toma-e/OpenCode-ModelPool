# Jules Autonomous Coding Agent Instructions : OpenCode-ModelPool 🤖

Bienvenue sur **OpenCode-ModelPool**. Vous opérez en tant qu'agent de développement autonome **Jules** (Google Labs).
Ce fichier constitue votre point d'ancrage prioritaire à la racine du dépôt.

---

## 🔒 Invariants Architecturaux Non-Négociables

1. **Pureté Fonctionnelle Stricte** :
   - `src/selector.py` et `src/exporter.py` sont des modules exclusivement composés de **fonctions pures**.
   - STRICTEMENT AUCUN appel I/O disque (`open()`), réseau (`urllib`, `socket`) ou dépendance non déterministe (`random`, `time`).
   - Tout accès fichier et persistance est confiné dans `src/service.py` et `src/fetcher.py`.

2. **Zéro Dépendance Externe au Runtime** :
   - Le cœur logiciel de production (`src/`, `main.py`) utilise UNIQUEMENT la bibliothèque standard Python (`stdlib`).
   - Ne JAMAIS ajouter de paquets tiers dans `pyproject.toml` sous `dependencies`. Les outils de test et linting (`pytest`, `ruff`, `mypy`) sont cantonnés à `[project.optional-dependencies] dev`.

3. **Discipline de Test Rigoureuse (TDD)** :
   - Tout bogue doit être reproduit par un test unitaire rouge dans `tests/test_*.py` avant d'être corrigé.
   - La suite de tests unitaires doit s'exécuter en moins d'une demi-seconde avec zéro échec :
     ```bash
     python3 -m unittest discover tests
     ```
   - La validation globale du parc d'agents doit être systématiquement vérifiée :
     ```bash
     python3 main.py --validate
     ```

4. **Sécurité Concurrente & Atomicité** :
   - Les écritures sur `data/models.json` et `config/opencode.json` doivent être atomiques (écriture temporaire puis renommage) et protégées par le verrou inter-processus (`.modelpool.lock`).

---

## ⚡ Commandes de Référence dans l'Environnement Cloud Jules

```bash
# 1. Installation des dépendances dev
python3 -m pip install -e '.[dev]'

# 2. Exécution des tests unitaires
python3 -m unittest discover tests

# 3. Validation de l'attribution des agents OpenCode
python3 main.py --validate

# 4. Vérification de l'export
python3 main.py --export

# 5. Contrôles statiques de qualité
python3 -m ruff check .
python3 -m mypy .
```

---

## 📚 Documentation Complète & Protocoles

Pour le guide complet de relecture de PR et le protocole détaillé de résolution de bogues, consultez :
- [`docs/google_ai_pro/jules/README.md`](../docs/google_ai_pro/jules/README.md)
- [`docs/google_ai_pro/jules/jules_instructions.md`](../docs/google_ai_pro/jules/jules_instructions.md)
- [`docs/google_ai_pro/jules/prompts/pr_review_prompt.md`](../docs/google_ai_pro/jules/prompts/pr_review_prompt.md)
- [`docs/google_ai_pro/jules/prompts/bugfix_workflow.md`](../docs/google_ai_pro/jules/prompts/bugfix_workflow.md)
- Guide de référence général : [`AGENTS.md`](../AGENTS.md)
