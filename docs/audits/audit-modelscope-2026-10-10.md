# 🔍 Audit Complet — ModelScope

*Généré le 10 octobre 2026 — 1 618 lignes de code, 24 tests, 386 modèles en catalogue*

---

## Vue d'ensemble

Le projet est fonctionnel, bien structuré et cohérent. L'architecture 4 modules + CLI tient la route. Mais l'audit révèle **3 bugs avérés**, **plusieurs lacunes de couverture de tests**, et **des améliorations structurantes** qui feraient passer le projet d'un MVP solide à un outil de production fiable.

---

## 🔴 Bugs Avérés (Priorité Haute)

### Bug 1 — Faux positifs dans `estimate_complexity_score` : substring matching
> **Fichier :** [src/fetcher.py#L48](src/fetcher.py#L48)

Le matching par substring `"1b" in m_id` capture les modèles dont l'ID contient `1b` comme sous-chaîne, même si ce n'est pas un modèle à 1 milliard de paramètres :

| Modèle | Score attribué | Score attendu |
|--------|---------------|--------------|
| `google/gemma-4-31b-it` | **1** (ultra-léger) | 3-4 (31B params) |
| `google/gemma-4-31b-it:free` | **1** | 3-4 |

**Même problème pour `"3b"`** : 14 modèles de type `30b-a3b` (architecture MoE, 30B actifs) sont classés en score 2 au lieu de 3-4 :
- `qwen/qwen3.6-35b-a3b` → score 2 au lieu de 4
- `qwen/qwen3-vl-30b-a3b-thinking` → score 2 au lieu de 4

**Cause :** Les regex pour les tailles de paramètres ne sont pas bornées par des séparateurs.

**Correction :** Utiliser des regex avec frontières de mot :
```python
# Avant (ligne 48)
if any(k in m_id for k in ["1b", "0.5b", "nano", "micro", "tiny"]):

# Après
import re
if re.search(r'(?:^|[-_/.])(?:1b|0\.5b)(?:[-_/.:$]|$)', m_id) or \
   any(k in m_id for k in ["nano", "micro", "tiny"]):
```

### Bug 2 — `o4-mini` classé en score 2 au lieu de 4-5
> **Fichier :** [src/fetcher.py#L38](src/fetcher.py#L38)

Les modèles de la série `o4` d'OpenAI (raisonnement avancé) ne sont pas reconnus par les patterns score-5 :
- `openai/o4-mini` → score **2** (mini regex match) au lieu de **4-5**
- `openai/o4-mini-high` → score **2** au lieu de **5**

Les patterns `o1` et `o3` sont couverts, mais pas `o4`.

**Correction :** Ajouter `"o4"` dans les patterns score 5, et gérer la variante `-mini` :
```python
if any(k in m_id for k in ["opus", "sonnet", "o1", "o3", "o4", "r1", ...]):
```

### Bug 3 — `microsoft/wizardlm-2-8x22b` classé score 1
> **Catalogue actuel**

Ce modèle MoE 8×22B (141B params totaux) est classé score 1 car son ID contient la sous-chaîne `"1b"` (dans `wizardlm-2-8x22**b**`). Il devrait être score 4-5.

---

## 🟡 Lacunes de Tests (Priorité Haute)

### Pas de `tests/__init__.py`
Les tests fonctionnent grâce à `unittest discover`, mais pytest et certains outils (mypy, coverage) peuvent échouer sans ce fichier.

### Pas de `tests/test_main.py`
Le CLI (`main.py`, 181 lignes) n'a aucun test :
- Pas de test du parsing argparse (`--sync`, `--export`, `--no-fallback`)
- Pas de test de `load_data()` — aucune validation que les fichiers JSON sont lus correctement
- Pas de test de la gestion d'erreur quand `models.json` n'existe pas

### Fonctions non testées directement

| Module | Fonctions sans test direct |
|--------|---------------------------|
| `selector.py` | `check_common_constraints`, `Model.is_free`, `Model.total_cost_per_m`, `Model.from_dict`, `AgentRequirement.from_dict` |
| `fetcher.py` | `fetch_openrouter_models`, `sync_models_from_openrouter` |
| `budget.py` | `FleetBudgetReport.has_budget_warnings` |

> [!NOTE]
> Certaines de ces fonctions sont testées *indirectement* via les fonctions de plus haut niveau (ex: `from_dict` est utilisé via `rank_models_for_agent`). Mais un test direct offre une meilleure localisation des régressions.

### Cas limites manquants

| Scénario | Module concerné |
|----------|----------------|
| Liste de modèles vide | `selector.py` — `rank_models_for_agent([])` |
| Agent sans description | `selector.py` — `AgentRequirement.from_dict({...})` avec clé manquante |
| Données JSON corrompues | `main.py` — `load_data()` sans try/except |
| Tokens négatifs | `budget.py` — `calculate_agent_cost()` avec des tokens < 0 |
| `allowed_providers` ET `excluded_providers` conflictuels | `selector.py` |
| `force_model` sur un modèle incompatible (tools, contexte) | `selector.py` — actuellement le modèle est retourné sans aucune vérification de compatibilité |
| Backup quand le disque est plein | `fetcher.py` |
| Timeout réseau | `fetcher.py` — `fetch_openrouter_models()` |

---

## 🟡 Points d'Architecture (Priorité Moyenne)

### 1. `force_model` ne valide rien
> **Fichier :** [src/selector.py#L241-L257](src/selector.py#L241-L257)

Quand `force_model` est défini, le modèle est retourné **sans vérifier** :
- S'il supporte les tools requis
- Si sa fenêtre de contexte est suffisante
- Si son provider est autorisé
- Si son coût respecte le budget

C'est un choix de design assumé (forçage = override total), mais dangereux. Au minimum, un **warning** dans `SelectionResult.reason` signalerait les incompatibilités.

### 2. Double parsing des modèles dans `resolve_model_for_agent`
> **Fichier :** [src/selector.py#L228-L294](src/selector.py#L228-L294)

`resolve_model_for_agent` parse les modèles (L238), puis appelle `rank_models_for_agent` qui les re-parse (L200). Avec 386 modèles, c'est 772 instanciations de `Model` inutiles.

```python
# Ligne 238 — premier parsing
parsed_models = [m if isinstance(m, Model) else Model.from_dict(m) for m in models]

# Ligne 260 — rank_models_for_agent fait le même parsing
exact_candidates = rank_models_for_agent(req, parsed_models, allow_fallback=False)
# → dans rank_models_for_agent, ligne 200 :
#   parsed_models = [m if isinstance(m, Model) else Model.from_dict(m) for m in models]
```

La garde `isinstance` rend ça inoffensif en termes de correction, mais ça alourdit le code.

### 3. Pas de validation de schéma pour `agents_requirements.json`
Aucun JSON Schema, aucune validation à l'exécution. Si un champ manque ou est mal typé, l'erreur n'est ni claire ni explicite :
- `"min_complexity"` absent → `KeyError` brut
- `"requires_tools": "yes"` → `bool("yes")` donne silencieusement `True`

### 4. `main.py` est un bloc monolithique
La fonction `main()` fait 140 lignes et mélange :
- Parsing CLI
- Chargement de fichiers
- Logique métier (résolution)
- Affichage formaté (couleurs ANSI)
- Export

Pas de séparation présentation / logique. Difficilement testable et pas réutilisable.

### 5. Pas de logging
Aucune utilisation du module `logging`. Tout passe par `print()` avec des codes ANSI. Impossible de :
- Filtrer les niveaux de verbosité
- Rediriger vers un fichier
- Intégrer dans un pipeline CI

---

## 🟢 Améliorations Mineures (Priorité Basse)

### Code

| Constat | Fichier | Détail |
|---------|---------|--------|
| `typing.List`, `typing.Dict` obsolètes | Tous | Python 3.11+ permet `list[...]`, `dict[...]` nativement. `from typing import List, Dict` est inutile. |
| `datetime.now()` sans timezone | [fetcher.py#L133](src/fetcher.py#L133), [exporter.py#L149](src/exporter.py#L149) | `datetime.now()` produit un datetime naïf (sans TZ). Utiliser `datetime.now(timezone.utc)` pour la traçabilité. |
| Pas de `__all__` dans les modules | `src/*.py` | Rend l'API publique implicite. |
| `Sequence[Union[Model, dict]]` partout | [selector.py](src/selector.py) | L'acceptation de `dict` dans les signatures de `rank_models_for_agent` et `resolve_model_for_agent` dilue le typage. Mieux vaut séparer parsing (dans `main.py`) et logique pure (dans `selector.py`). |
| `is_free` a une double logique | [selector.py#L29-L33](src/selector.py#L29-L33) | `tier == "free_tier"` OU `cost == 0`. Redondant avec le parsing dans `fetcher.py` qui fixe déjà le `tier` en fonction du coût. |

### Données

| Constat | Impact |
|---------|--------|
| `data/models.json` daté du 8 octobre 2026 | Pas de freshness check. Le CLI ne prévient pas si le catalogue est vieux de plusieurs semaines. |
| Pas de versioning du schéma de `models.json` | Le champ `"version": "1.0"` existe mais n'est jamais vérifié à la lecture. |
| Les backups s'accumulent sans rotation | `data/backups/` peut grossir indéfiniment. Pas de politique de rétention. |

### Packaging & CI

| Constat | Impact |
|---------|--------|
| `pyproject.toml` déclare `dependencies = []` | Correct (stdlib uniquement), mais `requests` pourrait remplacer `urllib.request` pour la robustesse. |
| Pas de CI/CD | Pas de GitHub Actions, pas de pre-commit hooks. |
| `mypy --strict` déclaré mais jamais exécuté en CI | Configuration dans `pyproject.toml` mais pas d'intégration. |
| Pas de `py.typed` marker | Le package ne sera pas reconnu comme typé par les consommateurs. |

---

## 📊 Résumé par Priorité

```
┌─────────────────────────────────────────────────────────┬──────────┬────────┐
│ Constat                                                 │ Sévérité │ Effort │
├─────────────────────────────────────────────────────────┼──────────┼────────┤
│ 🔴 Bug: substring matching dans estimate_complexity     │ Haute    │ Faible │
│ 🔴 Bug: o4-mini non reconnu comme raisonnement          │ Haute    │ Faible │
│ 🔴 Bug: wizardlm-2-8x22b classé score 1                │ Haute    │ Faible │
│ 🟡 Pas de tests pour main.py                            │ Haute    │ Moyen  │
│ 🟡 force_model sans validation de compatibilité         │ Moyenne  │ Faible │
│ 🟡 Pas de validation JSON Schema des configs            │ Moyenne  │ Moyen  │
│ 🟡 main.py monolithique / pas de logging                │ Moyenne  │ Moyen  │
│ 🟡 Double parsing des modèles                           │ Basse    │ Faible │
│ 🟢 typing obsolète (List → list)                        │ Basse    │ Faible │
│ 🟢 datetime naïf sans timezone                          │ Basse    │ Faible │
│ 🟢 Pas de rotation des backups                          │ Basse    │ Faible │
│ 🟢 Pas de CI/CD GitHub Actions                          │ Basse    │ Moyen  │
└─────────────────────────────────────────────────────────┴──────────┴────────┘
```

---

## ✅ Points Positifs

- **Architecture propre** : séparation claire fetcher → selector → budget → exporter
- **Invariant `frozen=True`** respecté sur toutes les dataclasses — pas de mutation accidentelle
- **`selector.py` est purement fonctionnel** : zéro I/O, facilement testable
- **Backup automatique** avant chaque sync — sécurité des données
- **24 tests passent** sans erreur ni warning
- **Documentation multi-agents** exhaustive et cohérente entre fichiers
- **`.gitignore` bien configuré** : exclut backups, caches, IDE
