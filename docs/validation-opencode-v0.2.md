# Protocole de Validation de Bout en Bout OpenCode — V0.2 🧪

Ce document définit le protocole officiel de validation en conditions réelles d'**OpenCode-ModelPool V0.2** couplé avec l'outil CLI **OpenCode**. Il couvre les exigences du ticket **MP-208** (Validation réelle) et sert de référence d'acceptation pour la release V0.2.

---

## 1. Pré-requis & Environnement de Test

### Fiche d'Environnement

| Paramètre | Spécification Minimale | Exemple de Valeur |
|---|---|---|
| **Système d'Exploitation** | Linux (Ubuntu 22.04+), WSL2 ou Windows 10/11 | Linux x86_64 / Ubuntu 24.04 |
| **Python** | 3.11 ou supérieur | Python 3.12 / 3.14 |
| **OpenCode CLI** | Version officielle installée et accessible dans `$PATH` | `opencode --version` |
| **Fournisseurs d'accès** | Au moins une clé valide (OpenRouter, Google, Mistral, Groq, Cerebras) ou Ollama local | Variable d'environnement ou `~/.env` |

---

## 2. Procédure de Validation Étape par Étape

### Étape 1 : Diagnostic des clés et accès locaux
Vérifier que les clés d'environnement et connecteurs sont correctement reconnus sans divulgation de secrets :
```bash
python3 main.py --status-keys
```
- **Résultat attendu** :
  - Tableau des fournisseurs avec état `✅ Oui` ou `❌ Non`.
  - Masquage strict des clés API (ex: `sk-or...`, `AQ.A...`).
  - Modèles vérifiés affichés si un rafraîchissement d'accès a déjà eu lieu.

### Étape 2 : Validation structurelle d'attribution
Vérifier que chaque agent du parc dispose d'un modèle compatible au catalogue :
```bash
python3 main.py --validate
```
- **Résultat attendu** : Code de sortie `0` et confirmation `✅ Validation réussie : tous les agents disposent d'un modèle compatible.`

### Étape 3 : Contrôle strict d'exécutabilité (`--check-ready`)
Vérifier que chaque modèle attribué dispose d'un canal prouvé (clé d'API active et validée, ou service local Ollama opérationnel) :
```bash
python3 main.py --check-ready
```
- **Résultats attendus** :
  - Si un fournisseur manque ou si la clé n'est pas vérifiée : échec explicite (code de sortie `1`) listant précisément les agents non opérationnels.
  - Si toutes les cibles sont prêtes : code de sortie `0` et confirmation `✅ Contrôle strict d'exécutabilité réussi`.

### Étape 4 : Prévisualisation sécurisée (`--diff`)
Vérifier les modifications avant d'écrire sur la configuration active :
```bash
python3 main.py --diff config/opencode.json
```
- **Résultat attendu** :
  - Affichage d'un diff unifié des modifications.
  - Validation du schéma officiel OpenCode avant écriture.

### Étape 5 : Export effectif & Sauvegarde automatique
Générer la configuration OpenCode et le rapport d'audit :
```bash
python3 main.py --export config/opencode.json
```
- **Résultat attendu** :
  - Création/mise à jour atomique de `config/opencode.json`.
  - Génération de `config/modelpool-report.json`.
  - Création automatique d'une sauvegarde horodatée (`data/backups/`) ou `.bak`.

---

## 3. Matrice de Tests Fonctionnels des 4 Agents OpenCode

Une fois la configuration exportée vers OpenCode (soit localement, soit dans `~/.config/opencode/opencode.json`), exécuter la suite de tests fumigènes sur chaque agent représentatif.

### Test 1 : Agent `build` (Mode Primary — Droits d'écriture)
- **Objectif** : Vérifier que l'agent `build` dispose des outils de modification de code et des permissions d'édition.
- **Commande** :
  ```bash
  opencode run --agent build "Ajoute un commentaire '# Test OpenCode build' dans README.md"
  ```
- **Critères d'acceptation** :
  - Modèle attribué chargé via son canal natif (ex: `mistral/codestral-latest`).
  - L'agent utilise l'outil d'écriture pour modifier le fichier cible.
  - Permission accordée (`edit: allow`).

### Test 2 : Agent `plan` (Mode Primary — Lecture seule / Pas d'édition)
- **Objectif** : Vérifier que l'agent `plan` analyse l'architecture sans pouvoir modifier de fichiers.
- **Commande** :
  ```bash
  opencode run --agent plan "Analyse l'architecture du projet et propose un plan pour ajouter un nouveau provider"
  ```
- **Critères d'acceptation** :
  - L'agent lit les fichiers via ses outils de lecture.
  - L'agent produit le plan d'action sans créer ni modifier de fichier sur disque (`permission: {"edit": "deny"}`).

### Test 3 : Agent `explore` (Mode Subagent — Recherche dans le code)
- **Objectif** : Vérifier que l'agent `explore` parcourt le dépôt pour retrouver des références.
- **Commande** :
  ```bash
  opencode run --agent explore "Retrouve où est défini ExecutionTarget et cite le fichier et la ligne"
  ```
- **Critères d'acceptation** :
  - L'agent retrouve `src/providers/router.py`.
  - Aucune modification de fichier autorisée (`permission: {"edit": "deny"}`).

### Test 4 : Agent `general` (Mode Subagent — Tâches diverses)
- **Objectif** : Vérifier le fonctionnement de l'agent polyvalent pour des explications ou synthèses.
- **Commande** :
  ```bash
  opencode run --agent general "Résume en 3 points le rôle d'OpenCode-ModelPool"
  ```
- **Critères d'acceptation** :
  - Synthèse correcte et claire produite.

---

## 4. Test de Restauration d'Urgence (`--rollback`)

En cas d'export corrompu ou rejeté :
```bash
python3 main.py --rollback config/opencode.json
```
- **Critères d'acceptation** :
  - Restauration de la sauvegarde précédente.
  - Intégrité vérifiée sans corruption de fichier.

---

## 5. Règles de Sécurité et Politiques Financières

1. **Zéro dépense imprévue** : Les tests unitaires automatisés (`python3 -m unittest discover tests`) ne consomment **aucun token payant** et s'exécutent entièrement hors ligne via mocks et simulations.
2. **Absence de secrets** : Les rapports d'audit `modelpool-report.json`, la console CLI et les sorties web ne divulguent aucune clé d'API en clair.
