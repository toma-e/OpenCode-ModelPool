# NotebookLM : Mémoire Architecturale Continue & Radar de Modèles 🧠

## 1. Rôle et Mission

Dans l'écosystème OpenCode-ModelPool, **NotebookLM** assure deux fonctions stratégiques majeures :
1. **Mémoire Architecturale Continue (Zero-Hallucination Grounding)** :
   - Fournit une base de connaissances interactive infaillible, strictement ancrée dans le code source et la documentation du projet (`AGENTS.md`, `README.md`, configurations).
   - Permet aux développeurs et aux agents d'ingénierie d'évaluer instantanément l'impact architectural d'une modification avant d'écrire la moindre ligne de code.
2. **Radar de Parution et Analyse d'Aptitude des Modèles** :
   - Évalue les annonces et rapports techniques de nouveaux LLMs par rapport aux 4 rôles d'agents OpenCode (`build`, `plan`, `explore`, `general`).
   - Recommande le score de complexité approprié (1 à 5) et le positionnement économique (gratuit vs payant).
3. **Génération de Synthèses Audio (Audio Overviews)** :
   - Produit des podcasts techniques animés par deux intervenants synthétiques pour résumer les jalons franchis, les arbitrages budgétaires et les choix d'architecture.

---

## 2. Ingestion & Capacités

NotebookLM repose sur un ancrage exclusif sur les sources fournies :
- **Plafonds par source** : Jusqu'à 500 000 mots ou 200 Mo par document.
- **Plafond par carnet** : Jusqu'à 50 sources documentaires.
- **Principe de fidélité** : Si une information n'est pas présente dans les sources, NotebookLM l'indique explicitement au lieu d'extrapoler.

Consultez le guide détaillé [`source_ingestion_guide.md`](source_ingestion_guide.md) pour la constitution du carnet.

---

## 3. Documents et Prompts Disponibles

| Document | Rôle |
|---|---|
| [`source_ingestion_guide.md`](source_ingestion_guide.md) | Guide méthodologique de sélection, découpage et téléversement des sources |
| [`sources/curated_sources.json`](sources/curated_sources.json) | Répertoire des URLs de documentation officielle et flux RSS de parutions |
| [`prompts/architecture_grounding.md`](prompts/architecture_grounding.md) | Prompts d'analyse d'impact et de vérification des invariants purs |
| [`prompts/model_release_eval.md`](prompts/model_release_eval.md) | Grille d'évaluation d'un nouveau modèle pour les 4 rôles OpenCode |
| [`prompts/audio_overview_brief.md`](prompts/audio_overview_brief.md) | Canevas structuré pour la génération d'un épisode Audio Overview |

---

## 4. Protocole d'Utilisation

1. Créez un nouveau carnet dans [notebooklm.google.com](https://notebooklm.google.com) nommé **`OpenCode-ModelPool — Architecture & Release Radar`**.
2. Téléversez les sources prioritaires du dépôt listées dans [`sources/curated_sources.json`](sources/curated_sources.json).
3. Utilisez les prompts standardisés pour obtenir des analyses documentées et sourcées.
