# Suivi — Interface Web locale

*Créé le 10 octobre 2026 après le correctif de fiabilité `8bbfc76`.*

## État vérifié

- Les 34 tests unitaires, Ruff et mypy passent.
- Le moteur de sélection (`src/selector.py`) reste pur et ne doit recevoir ni I/O,
  ni HTTP, ni représentation HTML.
- Le CLI centralise encore le chargement de fichiers, l'orchestration, le rendu et
  l'export dans `main.py` : une interface ne doit pas réutiliser ses sorties texte.
- Le catalogue est synchronisé depuis OpenRouter (375 modèles) et l'export OpenCode
  est généré depuis les résultats de sélection.

## Décision d'architecture

La première interface sera une application Web **locale uniquement**, liée à
`127.0.0.1`. Elle n'introduira aucune dépendance d'exécution externe : serveur,
routage et JSON utiliseront la bibliothèque standard Python.

```text
CLI                 Interface Web locale
 │                            │
 └──────────────┐   ┌─────────┘
                ▼   ▼
          Service applicatif
    chargement · sélection · budget · export · sync
                         │
                         ▼
       Moteur pur : selector + budget + exporter
```

Le service applicatif deviendra la seule couche qui connaît les chemins de fichiers
et les opérations à effet de bord. Le CLI et les routes HTTP l'appelleront sans
dupliquer la logique métier. Les modules `selector.py` et `budget.py` conserveront
leurs contrats purs et déterministes.

## Périmètre de la première passe

1. Extraire depuis `main.py` un service renvoyant un rapport structuré : catalogue,
   résultats par agent, simulation budgétaire et éventuels diagnostics.
2. Ajouter une commande pour démarrer le serveur local et servir une page unique.
3. Afficher les affectations, modèles alternatifs, coûts, quotas, fallback et
   contraintes contournées par un `force_model`.
4. Proposer des actions explicites : recalculer, exporter la configuration et
   synchroniser le catalogue. Toute action d'écriture affiche son résultat ou son
   erreur sans exposer le serveur sur le réseau.
5. Garder `agents_requirements.json` en lecture seule pour cette version ; son
   édition sera une passe distincte avec validation et sauvegarde.

## Risques et prérequis à traiter

- Rendre l'écriture du catalogue atomique (fichier temporaire puis remplacement)
  afin qu'un arrêt pendant la synchronisation ne laisse pas de JSON corrompu.
- Ajouter une politique de rétention configurable aux backups horodatés.
- Sérialiser les synchronisations et exports pour éviter les écritures concurrentes.
- Tester le service indépendamment, puis les routes HTTP via un serveur de test ;
  couvrir les erreurs de chargement, réseau et écriture.
- Conserver l'absence de dépendances runtime et la compatibilité Python 3.11+.

## Critères d'acceptation

- Une exécution locale ouvre une interface utilisable sans accès externe.
- Le CLI et le Web produisent les mêmes résultats pour les mêmes fichiers.
- Une panne réseau ou une erreur de données devient un message UI clair, sans
  modifier le catalogue existant.
- Tous les tests existants restent verts et de nouveaux tests couvrent le service
  et les opérations HTTP critiques.
