# Guide d'Ingestion des Sources pour NotebookLM 📚

Ce guide détaille la procédure de préparation, de nettoyage et d'ingestion des documents du projet OpenCode-ModelPool dans Google NotebookLM afin de garantir un ancrage à 100% sans hallucination.

---

## 1. Contraintes & Limites Techniques de NotebookLM

Avant de téléverser des documents, prenez en compte les plafonds de la plateforme :
- **Plafond de volume par source** : 500 000 mots ou 200 Mo maximum.
- **Nombre maximal de sources par carnet** : 50 sources.
- **Formats supportés** : Fichiers Markdown (`.md`), Texte brut (`.txt`), Documents PDF (`.pdf`), Google Docs, Liens web (URLs) et vidéos YouTube (disposant de sous-titres/transcription).
- **Format non supporté / à risque** : Fichiers PDF scannés sans OCR, vidéos YouTube sans sous-titres, pages web protégées par un paywall ou un écran de connexion.

---

## 2. Stratégie de Découpage et Groupement (Bundling)

Afin d'optimiser le quota de 50 sources sans disperser l'information, regroupez les petits fichiers connexes sous forme de **faisceaux thématiques (bundles)**.

### Faisceau 1 : Invariants Architecturaux & Règles Développeur
- **Contenu** : `AGENTS.md` + `.cursorrules` + `.jules/instructions.md` + `README.md`.
- **Nom de la source** : `01_Architecture_Invariants_and_Conventions.md`.
- **Rôle** : Fournit le cadre normatif strict, la règle des fonctions pures et l'organisation du code.

### Faisceau 2 : Spécifications et Schémas OpenCode
- **Contenu** : `config/agents_requirements.json` + `Ressources/opencode.jsonc` + structure d'export.
- **Nom de la source** : `02_OpenCode_Requirements_and_Schemas.md`.
- **Rôle** : Définit les contraintes des 4 agents (`build`, `plan`, `explore`, `general`) et le schéma officiel attendu par OpenCode.

### Faisceau 3 : Synthèse de la Logique Métier
- **Contenu** : Extraits commentés de `src/selector.py` (classes `Model` et `AgentRequirement`, logique de tri et fallback), `src/budget.py` (calcul des coûts et alertes free-tier) et `src/providers/router.py`.
- **Nom de la source** : `03_Business_Logic_Contracts.md`.
- **Rôle** : Permet à NotebookLM de raisonner avec exactitude sur les algorithmes d'attribution et de surclassement économique.

### Faisceau 4 : Historique des Audits et Jalons
- **Contenu** : `docs/audits/audit-modelscope-2026-10-10.md` + `docs/audits/suivi-interface-web-2026-10-10.md`.
- **Nom de la source** : `04_Audit_History_and_Milestones.md`.
- **Rôle** : Historique des décisions passées (accélération des tests à 0.16s, correction DNS Rebinding, renommage).

### Faisceau 5 : Catalogue Modèles Filtré
- **Contenu** : Extrait représentatif de `data/models.json` (les modèles Tier 1 et modèles gratuits phares).
- **Nom de la source** : `05_Reference_Catalog_Extract.md`.
- **Note** : Ne téléversez pas l'intégralité du fichier brut de 378 entrées si des formats plus lisibles en Markdown suffisent.

---

## 3. Checklist d'Ingestion Pas-à-Pas

- [ ] **Étape 1 : Création du carnet**
  - Rendez-vous sur [notebooklm.google.com](https://notebooklm.google.com).
  - Cliquez sur "Nouveau carnet" et nommez-le : `OpenCode-ModelPool — Architecture & Release Radar`.

- [ ] **Étape 2 : Préparation des faisceaux**
  - Utilisez un script d'assemblage ou concaténez les fichiers markdown à l'aide de séparateurs clairs (ex: `=== Fichier: AGENTS.md ===`).

- [ ] **Étape 3 : Téléversement des sources internes**
  - Importez les faisceaux 1 à 5 sous forme de fichiers texte/markdown.
  - Vérifiez dans le panneau de gauche que le nombre de mots et le statut d'ingestion sont validés (coche verte).

- [ ] **Étape 4 : Ajout des sources de veille externes**
  - Ajoutez les URLs officielles de documentation indiquées dans `sources/curated_sources.json` (Google AI Studio, OpenAI pricing, Mistral docs, OpenRouter models).

- [ ] **Étape 5 : Test de calage (Sanity Check)**
  - Posez la question suivante dans NotebookLM :
    > *"Quels sont les 4 agents définis dans OpenCode-ModelPool et quelles sont leurs exigences respectives en matière de complexité et de support d'outils ?"*
  - Si la réponse mentionne exactement `build`, `plan`, `explore`, `general` avec leurs seuils de complexité et cite `02_OpenCode_Requirements_and_Schemas.md`, le carnet est correctement ancré.

---

## 4. Routine de Maintien en Condition Opérationnelle
Lorsque le code ou la configuration évolue (ex: nouveau jalon complété ou ajout d'un agent) :
1. Mettez à jour le faisceau correspondant en local.
2. Dans NotebookLM, supprimez l'ancienne version de la source et téléversez le faisceau actualisé.
3. NotebookLM réindexera instantanément l'ensemble des connaissances sans impacter les notes existantes.
