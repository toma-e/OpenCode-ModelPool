# Instructions pour l'Agent Autonome Jules : OpenCode-ModelPool 🛠️

Vous opérez en tant que **Jules**, ingénieur logiciel autonome de Google Labs, sur le dépôt **OpenCode-ModelPool**.

---

## 🔒 Invariants Architecturaux Impératifs

1. **Isolation Pure vs I/O** :
   - `src/selector.py` et `src/exporter.py` sont des modules de **transformation pure**. Ils ne doivent JAMAIS importer `urllib`, `socket`, `open()`, ni dépendre de l'heure système ou de générateurs pseudo-aléatoires.
   - Les accès au système de fichiers, sauvegardes et interactions réseau sont strictement réservés à `src/service.py`, `src/fetcher.py`, et `src/providers/`.
2. **Bibliothèque Standard Uniquement pour le Runtime** :
   - Le moteur de production (`main.py`, `src/`) s'exécute exclusivement avec la bibliothèque standard Python (`stdlib`).
   - N'ajoutez AUCUNE dépendance externe à `pyproject.toml` en dehors de la section `[project.optional-dependencies] dev`.
3. **Sécurité et Concurrence** :
   - Toute écriture de configuration ou mise à jour de catalogue doit être protégée par le verrou inter-processus (`.modelpool.lock` dans `ApplicationService`).
   - La synchronisation réseau ne doit pas bloquer les lecteurs locaux (téléchargement hors verrou).
4. **Schéma Officiel OpenCode Strict** :
   - La structure exportée dans `config/opencode.json` doit scrupuleusement respecter le schéma OpenCode (`additionalProperties: false`, format de modèle avec préfixe de fournisseur `openrouter/`, `ollama/`, `google/`, etc.).

---

## ⚡ Commandes d'Exécution dans la VM Cloud

### 1. Installation de l'Environnement de Développement
```bash
python3 -m pip install -e '.[dev]'
```

### 2. Exécution de la Suite de Tests
```bash
python3 -m unittest discover tests
```
*Critère de succès : 100% des tests doivent passer en moins d'une seconde sans régression.*

### 3. Validation de l'Attribution du Parc d'Agents
```bash
python3 main.py --validate
```
*Critère de succès : Tous les agents ('build', 'plan', 'explore', 'general') doivent recevoir une attribution valide.*

### 4. Contrôles Statiques (Linting & Typage)
```bash
python3 -m ruff check .
python3 -m mypy .
```

---

## 📋 Méthodologie de Travail pour une Tâche / Issue

1. **Reproduction par le Test** :
   - Écrivez toujours d'abord un test unitaire rouge dans `tests/test_*.py` qui reproduit l'anomalie ou spécifie la nouvelle fonctionnalité.
2. **Implémentation Minimale** :
   - Modifiez le code source de manière chirurgicale sans refactoring non sollicité.
   - Respectez les conventions de nommage et le style existant.
3. **Validation Complète** :
   - Lancez `python3 -m unittest discover tests` et `python3 main.py --validate`.
   - Assurez-vous que l'anomalie est résolue et qu'aucune régression n'apparaît.
4. **Ouverture de la Pull Request** :
   - Titrez la PR avec la convention Conventional Commits (ex: `fix(selector): corriger le départage en cas d'égalité tarifaire`).
   - Décrivez l'anomalie, la cause racine, le test de non-régression ajouté, et le résultat des commandes de validation.
