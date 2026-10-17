# Prompts NotebookLM : Cadrage Architectural & Analyse d'Impact 🏗️

Ces requêtes sont conçues pour être soumises directement dans le carnet NotebookLM **`OpenCode-ModelPool — Architecture & Release Radar`**. Elles exploitent l'ancrage strict sur les sources ingérées pour fournir des réponses documentées, assorties de citations exactes.

---

## Requête 1 : Fonctionnement de l'Attribution et du Surclassement Économique

```text
En vous basant exclusivement sur les sources ingérées d'OpenCode-ModelPool :

1. Décrivez de manière séquentielle le processus de sélection d'un modèle pour un agent donné :
   - Quels sont les filtres stricts appliqués en premier lieu (complexité, outils, vision, raisonnement, contexte, fournisseurs) ?
   - Comment s'articule la préférence pour le niveau gratuit ('prefer_free') avec le tri par coût ('lowest_cost') ?
   - Quel est le mécanisme de départage déterministe en cas d'égalité tarifaire parfaite ?
2. Expliquez le fonctionnement du mécanisme de surclassement économique (fallback) :
   - Dans quel cas précis s'active-t-il ?
   - Quelles contraintes techniques sont préservées lors du surclassement ?
   - Quel critère économique est maximisé lors du choix du modèle de substitution ?
3. Indiquez les noms exacts des fonctions et des fichiers sources qui régissent ce comportement.
```

---

## Requête 2 : Analyse d'Impact Architectural (Ajout d'une Contrainte Métier)

```text
Nous envisageons d'ajouter une nouvelle contrainte technique optionnelle pour les agents OpenCode :
'requires_structured_output: bool' (exigeant que le modèle garantisse des sorties JSON strictes).

À partir des documents d'architecture ingérés :
1. Quels fichiers du projet devront obligatoirement être modifiés ?
   - Distinguez précisément les modules de logique pure sans I/O (src/selector.py, src/exporter.py), les schémas de configuration (config/agents_requirements.json, Ressources/opencode.jsonc), et la couche d'orchestration (src/service.py, main.py).
2. Quels invariants architecturaux stricts énoncés dans AGENTS.md devront être scrupuleusement respectés :
   - Concernant les dépendances externes au runtime ?
   - Concernant la séparation des entrées/sorties et la pureté des fonctions ?
   - Concernant la vitesse et l'indépendance de la suite de tests unitaires ?
3. Rédigez le plan de test unitaire minimal requis dans tests/test_selector.py pour valider cette nouvelle exigence sans régression.
```

---

## Requête 3 : Analyse du Routage Multi-Fournisseurs et Priorité des Canaux

```text
En vous appuyant sur la documentation des jalons 16 et 17 dans AGENTS.md et sur la synthèse de la logique métier :

1. Comment s'articule le choix du canal d'exécution effectif pour un modèle sélectionné ?
   - Expliquez la hiérarchie entre : canal local Ollama (port 11434), canal Direct Provider (Google, Mistral, Groq, Cerebras, Anthropic) et canal Proxy OpenRouter.
   - Comment le paramètre '--provider-priority' influence-t-il cette décision ?
2. Quel est le rôle du fichier 'data/provider_access.json' et de la commande '--refresh-access' ?
   - Pourquoi le système refuse-t-il d'attribuer un canal direct si le modèle n'a pas été explicitement validé par la sonde dynamique ?
   - Quel est le comportement de repli (fallback de canal) si une clé API est configurée mais ne donne pas accès au modèle souhaité ?
```

---

## Requête 4 : Audit de Résilience & Concurrence (Verrouillage Inter-Processus)

```text
En consultant les comptes-rendus d'audit et les conventions de développement :

1. Pourquoi le fichier verrou '.modelpool.lock' a-t-il été introduit dans le projet ?
2. Comment l'architecture garantit-elle la portabilité du verrouillage inter-processus à la fois sur les systèmes POSIX (Linux/macOS via fcntl.flock) et sous Windows natif (via msvcrt.locking) ?
3. Pourquoi la synchronisation réseau avec OpenRouter est-elle effectuée EN DEHORS du verrou inter-processus (élimination du head-of-line blocking) ?
```
