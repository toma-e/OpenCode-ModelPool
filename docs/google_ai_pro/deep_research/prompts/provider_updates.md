# Prompt Gemini Deep Research : Veille des APIs, Endpoints & Dépréciations

## Contexte & Objectif
Vous êtes un ingénieur d'intégration API et architecte système.
Votre mission est de surveiller les canaux de publication officiels, les journaux de modifications (changelogs), la documentation pour développeurs et les annonces de dépréciation des grands fournisseurs de LLMs afin d'anticiper les ruptures de service dans OpenCode-ModelPool.

---

## Fournisseurs & Endpoints Cibles
1. **Google AI Studio / Gemini API** :
   - Endpoints : `https://generativelanguage.googleapis.com/v1beta/models`
   - Veille : Évolution des séries Gemini 2.5, Gemini 3.x, dépréciation définitive des versions antérieures (1.5 Pro/Flash).
2. **Mistral AI Platform** :
   - Endpoints : `https://api.mistral.ai/v1/models`
   - Veille : Nouvelles itérations de Codestral, Mistral Large, Mistral Small et modèles compacts Ministral.
3. **Groq Cloud API** :
   - Endpoints : `https://api.groq.com/openai/v1/models`
   - Veille : Mises à jour des modèles open-weights accélérés par LPU (Llama 3.3, Qwen 2.5 Coder, DeepSeek R1 distillés).
4. **Cerebras Inference** :
   - Endpoints : `https://api.cerebras.ai/v1/models`
   - Veille : Disponibilité des modèles wafer-scale et évolution des débits d'inférence.
5. **Anthropic API** :
   - Endpoints : `https://api.anthropic.com/v1/models`
   - Veille : Cycles de vie des modèles Claude 3.5 et 3.7, dates de mise hors service des versions antérieures.
6. **OpenRouter API** :
   - Endpoints : `https://openrouter.ai/api/v1/models`
   - Veille : Nouvelles routes multi-fournisseurs, changements dans la structure des réponses ou des métadonnées de tarification.

---

## 🔍 Points de Contrôle Critiques
Pour chaque fournisseur, identifiez et documentez :
1. **Dépréciations et Fin de Vie (EOL)** :
   - Nom et identifiant exact du modèle concerné.
   - Date programmée d'arrêt de service (Sunset Date).
   - Modèle de remplacement recommandé par le fournisseur.
2. **Extensions de Fenêtres de Contexte** :
   - Nouveaux plafonds de tokens d'entrée/sortie.
   - Impact sur les agents OpenCode à forte intensité documentaire (`plan`, `build`).
3. **Évolution des Protocoles d'Appel d'Outils (Tool Calling)** :
   - Changements de compatibilité avec les schémas JSON Schema / function calling.
   - Support du mode strict (`strict: true`) ou de l'appel d'outils en parallèle.
4. **Modifications des Endpoints ou de l'Authentification** :
   - Nouvelles en-têtes obligatoires, versions d'API dépréciées (ex: passage de `v1` à `v2`).

---

## 📦 Livrables Attendus

### Livrable 1 : Calendrier des Dépréciations et Remplacements (Markdown)
| Fournisseur | Modèle Déprécié | Date d'Arrêt Prévue | Modèle de Remplacement Direct | Action Requise dans OpenCode-ModelPool |
|---|---|---|---|---|

### Livrable 2 : Tableau Synthétique des Nouvelles Parutions
| Fournisseur | ID Officiel | Statut (Stable/Beta/Preview) | Contexte | Support Outils | Score Complexité Conseillé (1-5) |
|---|---|---|---|---|---|

### Livrable 3 : Recommandations Techniques d'Alignement
- Fichiers impactés dans le projet :
  - `src/providers/direct.py` : Nouveaux modèles à ajouter dans les catalogues statiques directs.
  - `src/providers/access.py` : Adaptations éventuelles des sondes de détection dynamique.
  - `data/models.json` : Modèles à déclasser ou retirer.
