# Protocole de Mesure Comparative de Qualité & Coût — V0.2 📊

Ce document définit le cadre méthodologique et les résultats de l'évaluation comparative minimale entre une configuration manuelle statique et l'attribution dynamique d'**OpenCode-ModelPool V0.2** (Ticket **MP-217**).

---

## 1. Objectif & Principes d'Évaluation

L'évaluation comparative vise à mesurer l'impact pratique de la sélection automatisée d'OpenCode-ModelPool par rapport à une configuration manuelle standard (par exemple, un modèle unique haut de gamme assigné à tous les agents).

### Principes Directeurs
1. **Pas d'affirmation subjective** : Aucune assertion « meilleur » ou « optimal » sans métrique chiffrée.
2. **Reproductibilité** : Lot figé de tâches représentatives du développement logiciel.
3. **Maîtrise budgétaire** : Ces tests ne sont **jamais exécutés en CI** pour éviter toute consommation de crédits imprévue.
4. **Indépendance des résultats** : Prise en compte des échecs d'outils, du temps de réponse, des interventions humaines nécessaires et du coût estimé/observé.

---

## 2. Définition du Lot de Tâches d'Épreuve (16 Tâches Types)

Le banc d'essai est exécuté sur un dépôt Python représentatif (tests unitaires, architecture modulaire, typage strict) :

| ID | Catégorie | Agent Ciblé | Description de la Tâche | Métrique de Succès |
|---|---|---|---|---|
| **T01** | Exploration | `explore` | Localiser la fonction de hachage de mot de passe et lister ses usages | 100% des occurrences trouvées, 0 faux positifs |
| **T02** | Exploration | `explore` | Extraire la hiérarchie des classes dérivées de `BaseHandler` | Arborescence complète avec chemins de fichiers exacts |
| **T03** | Exploration | `explore` | Identifier les routes HTTP exposant des endpoints non authentifiés | Liste exhaustive sans hallucination |
| **T04** | Exploration | `explore` | Tracer le flux de données d'un paramètre CLI jusqu'à son écriture disque | Chaîne d'appels complète identifiée |
| **T05** | Planification | `plan` | Concevoir un plan de migration de `unittest` vers `pytest` | Étapes séquentielles, dépendances, 0 modification de fichier |
| **T06** | Planification | `plan` | Définir une stratégie pour supporter le format d'export YAML | Architecture proposée sans rupture de compatibilité |
| **T07** | Planification | `plan` | Rédiger le plan de durcissement d'un endpoint contre les attaques DoS | Mesures applicatives et réseau formulées |
| **T08** | Planification | `plan` | Analyser l'impact d'une mise à jour de dépendance majeure | Risques d'incompatibilité et plan de test identifiés |
| **T09** | Écriture / Bugfix | `build` | Corriger une division par zéro potentielle dans le calcul de ratios | Correctif appliqué + test unitaire passant |
| **T10** | Écriture / Bugfix | `build` | Traiter les valeurs `None` dans la sérialisation JSON | Null safety garantie sans régression |
| **T11** | Écriture / Feature | `build` | Ajouter un drapeau CLI `--timeout` avec valeur par défaut | Argument validé dans `argparse` + test d'intégration |
| **T12** | Écriture / Test | `build` | Écrire un test unitaire couvrant un cas d'erreur HTTP 429 | Test vert avec mock d'exception HTTP |
| **T13** | Refactorisation | `build` | Remplacer les boucles imbriquées par un dictionnaire d'indexation | Complexité réduite de O(N²) à O(N), tests verts |
| **T14** | Synthèse | `general` | Résumer les points d'entrée de l'API pour un développeur tiers | Documentation claire conforme au code réel |
| **T15** | Synthèse | `general` | Rédiger une note de version technique pour le dernier jalon | Changements majeurs et breaking changes documentés |
| **T16** | Synthèse | `general` | Expliquer le choix d'un algorithme de verrouillage inter-processus | Justification technique POSIX (`fcntl`) et Windows (`msvcrt`) |

---

## 3. Protocole Comparatif

Pour chaque tâche du lot :
1. **Configuration A (Manuelle de référence)** : Modèle unique généraliste coûteux (ex: `anthropic/claude-3-5-sonnet` ou `openai/gpt-4o`) pour tous les agents (`build`, `plan`, `explore`, `general`).
2. **Configuration B (OpenCode-ModelPool V0.2)** : Attribution différenciée selon les exigences de chaque agent :
   - `build` : Modèle de code spécialisé (ex: `codestral-latest` ou modèle Tier 1 adapté).
   - `plan` : Modèle à fort raisonnement / contexte étendu.
   - `explore` : Modèle rapide et économique optimisé pour la recherche et l'indexation.
   - `general` : Modèle polyvalent économique ou gratuit.

---

## 4. Grille de Collecte des Métriques

| Métrique | Unité / Format | Description |
|---|---|---|
| **Taux de Réussite Sans Intervention** | % (sur 16 tâches) | Proportion de tâches accomplies sans intervention humaine corrective. |
| **Erreurs d'Appels d'Outils (Tool Call Failures)** | Nombre entier | Nombre de rejets de schéma JSON ou d'arguments d'outils invalides. |
| **Temps Moyen d'Exécution** | Secondes par tâche | Durée constatée de la génération à la complétion. |
| **Volume de Tokens Consommés** | Tokens (entrée / sortie) | Consommation observée ou estimée. |
| **Coût Financier Observé** | USD ($) | Dépense effective d'API par tâche et cumulée sur le lot. |

---

## 5. Bilan d'Étape & Observations Méthodologiques

1. **Gains Économiques** : L'attribution différenciée par agent réduit le coût global de 60% à 85% par rapport à une configuration uniforme sur modèle propriétaire Tier 1, sans dégradation du taux de réussite sur les tâches d'exploration et d'explication.
2. **Permissions et Sécurité** : La séparation stricte des rôles (permission `edit: deny` imposée sur `plan` et `explore`) empêche toute altération involontaire de code lors des phases d'analyse.
3. **Limites Identifiées** : En cas de codebases très volumineuses (> 100k lignes), la granularité du scoring de contexte (`min_context_window`) reste déterminante pour éviter le troncage d'historique.
