# Prompt Gemini Deep Research : Benchmark Exhaustif des Tarifs & Capacités LLM

## Contexte & Objectif
Vous êtes un expert analyste en infrastructure d'Intelligence Artificielle et modélisation des coûts de calcul.
Votre mission est d'effectuer un audit approfondi, exhaustif et rigoureusement documenté des tarifs officiels des modèles de langage (LLMs) pour les tâches de développement et d'architecture de code.

---

## Fournisseurs & Plateformes Cibles
1. **Google AI Studio / Vertex AI** : Modèles Gemini (Gemini 2.5 Flash, 2.5 Pro, Flash-Lite, 3.x, Gemma 2/3/4).
2. **Anthropic** : Modèles Claude (Claude 3.5 Sonnet, Claude 3.5 Haiku, Claude 3.7 Sonnet).
3. **OpenAI** : Modèles GPT et séries O (GPT-4o, GPT-4o-mini, o1, o3, o4-mini).
4. **Mistral AI** : Modèles Mistral (Mistral Small, Large, Codestral, Pixtral, Ministral).
5. **Groq Cloud** : Modèles d'inférence ultra-rapide (Llama 3.3 70B, Qwen 2.5 Coder 32B).
6. **Cerebras** : Modèles d'accélération Wafer-Scale (Llama 3.1 8B, 70B).
7. **OpenRouter** : Agrégateur public (prix effectifs et variantes `:free` pour les modèles susmentionnés).

---

## ⛔ Périmètre Strict & Exclusions Impératives
- **INCLURE EXCLUSIVEMENT** : Les modèles génératifs de texte, de code informatique et de raisonnement multimodal textuel (LLM / VLM textuels).
- **EXCLURE STRICTEMENT** :
  - Les modèles de génération audio ou musicale (ex: Lyria, MusicLM, Suno).
  - Les modèles de transcription et de synthèse vocale / TTS (ex: Whisper, Gemini TTS, ElevenLabs).
  - Les modèles d'embeddings purs (ex: text-embedding-004, OpenAI ada/small/large).
  - Les modèles de génération d'images et de vidéos pures (ex: Imagen, Sora, Stable Diffusion).
  - Les modèles de robotique pure sans interface de chat/code.

---

## 📏 Règles de Normalisation
1. **Unité Monétaire et d'Usage** : Tous les prix DOIVENT être convertis en **USD ($) par Million (1 000 000) de tokens**. Si un fournisseur exprime ses tarifs par 1 000 tokens ou par token, multipliez impérativement par le facteur adéquat.
2. **Gestion des Paliers** : Si un fournisseur pratique des tarifs échelonnés (ex: < 128k tokens vs > 128k tokens), retenez le tarif de base (standard) et notez le tarif supérieur dans le rapport explicatif.
3. **Prompt Caching** : Mentionnez le pourcentage de réduction sur les tokens d'entrée mis en cache (`cache_read`), mais conservez le tarif standard d'entrée dans `cost_input_per_m`.
4. **Niveau de Service (`tier`)** : Doit valoir obligatoirement `"free_tier"` si le modèle est entièrement gratuit pour les développeurs, ou `"pay_as_you_go"` pour la facturation à l'usage.
5. **Score de Complexité (`complexity_score`)** : Entier compris entre 1 et 5 :
   - `1` : Modèle très léger / local / extraction simple (< 7B paramètres).
   - `2` : Modèle intermédiaire rapide pour exploration et lecture seule (8B à 14B).
   - `3` : Modèle équilibré polyvalent pour tâches générales et petits refactorings (14B à 35B).
   - `4` : Grand modèle d'ingénierie et de génération de code avancée (70B à 120B ou équivalent propriétaire).
   - `5` : Modèle de pointe (Frontier model) avec capacités de raisonnement complexe (`o1`, `o3`, `Claude Sonnet`, `Gemini Pro`).

---

## 📦 Livrables Attendus

### Livrable 1 : Tableau Comparatif Markdown
Un tableau synthétique complet :
| Fournisseur | ID Modèle Normalisé | Coût Entrée ($/1M) | Coût Sortie ($/1M) | Contexte (Tokens) | Support Tools | Vision | Raisonnement | Free Tier Dispo ? |
|---|---|---|---|---|---|---|---|---|

### Livrable 2 : Tableau JSON Structuré Machine-Readable
Un bloc JSON strictement conforme au schéma suivant (aucun champ manquant, aucun NaN/Infinity) :

```json
[
  {
    "id": "fournisseur/nom-du-modele",
    "provider": "google",
    "tier": "pay_as_you_go",
    "cost_input_per_m": 0.15,
    "cost_output_per_m": 0.60,
    "context_window": 1048576,
    "supports_tools": true,
    "complexity_score": 4,
    "supports_vision": true,
    "supports_reasoning": true,
    "source_url": "https://ai.google.dev/pricing"
  }
]
```

### Livrable 3 : Analyse des Tendances et Dépréciations
- Liste des baisses récentes de tarifs notables.
- Comparaison entre le coût direct du fournisseur et le coût sur OpenRouter.
- Modèles en fin de vie annoncés (date de retrait).
