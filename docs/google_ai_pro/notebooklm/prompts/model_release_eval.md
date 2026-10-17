# Prompt NotebookLM : Grille d'Évaluation des Nouvelles Parutions LLM 🎯

Ce prompt est destiné à être utilisé dans NotebookLM lors de la parution d'un nouveau modèle (après avoir téléversé le rapport technique, l'article de blog ou la fiche modèle correspondante dans les sources du carnet).

---

## Modèle de Requête d'Évaluation

```text
Un nouveau modèle de langage vient d'être annoncé : [INSÉREZ LE NOM DU MODÈLE ET SA FICHE TECHNIQUE].

En vous fondant sur la définition de nos 4 agents OpenCode dans 'config/agents_requirements.json' et sur les critères de qualification de 'AGENTS.md' :

### 1. Analyse d'Éligibilité Technique
Analysez la compatibilité du modèle avec chacun des 4 rôles :
- 'build' (Agent principal de code) :
  - Exigences : Complexité 4-5, support impératif des outils (tools), raisonnement approfondi (reasoning), contexte >= 64 000 tokens.
  - Le modèle satisfait-il l'ensemble de ces critères ?
- 'plan' (Agent principal d'architecture) :
  - Exigences : Complexité 4-5, capacités multimodales/vision obligatoires, raisonnement de pointe, contexte >= 64 000 tokens (outils d'écriture non requis).
  - Le modèle satisfait-il ces critères ?
- 'explore' (Sous-agent d'exploration rapide) :
  - Exigences : Complexité 2-3, très haute vitesse d'exécution, préférence pour la gratuité (prefer_free=true), lecture seule sans outils, contexte >= 32 000 tokens.
  - Le modèle est-il surdimensionné ou adapté ?
- 'general' (Sous-agent polyvalent) :
  - Exigences : Complexité 3-4, compromis coût/performance équilibré, support des outils, raisonnement requis, contexte >= 64 000 tokens.
  - Le modèle est-il un bon candidat ?

### 2. Attribution du Score de Complexité
En tenant compte du nombre de paramètres (actifs et totaux pour les architectures MoE) et des benchmarks de code (ex: SWE-bench, HumanEval, LiveCodeBench) :
- Quel score de complexité (entier entre 1 et 5) convient-il d'attribuer à ce modèle dans 'data/models.json' ?
- Justifiez ce choix par rapport aux modèles de référence existants.

### 3. Modélisation Économique & Budget Mensuel
En appliquant les volumes de consommation mensuels de nos agents :
- Si ce modèle était attribué à l'agent cible, quel serait son coût mensuel estimé ?
- Ce coût respecte-t-il le plafond budgétaire de l'agent (ex: 15$ pour build, 10$ pour plan, 2$ pour explore, 5$ pour general) ?
- Existe-t-il un risque de quota (rate-limiting) si le modèle est proposé sur un palier gratuit ?

### 4. Recommandation Finale & Extrait JSON
- Recommandation catégorique : Modèle retenu comme choix principal, modèle de repli (fallback), ou modèle exclu.
- Fournissez l'entrée JSON prête à être insérée dans 'data/models.json', conforme à la structure dataclass Model :
```json
{
  "id": "fournisseur/nom-exact-du-modele",
  "provider": "...",
  "tier": "free_tier ou pay_as_you_go",
  "cost_input_per_m": 0.0,
  "cost_output_per_m": 0.0,
  "context_window": 128000,
  "supports_tools": true,
  "complexity_score": 4,
  "supports_vision": false,
  "supports_reasoning": true
}
```
