# Prompt Gemini Deep Research : Surveillance des Quotas Free-Tier & Rate-Limits

## Contexte & Objectif
Vous êtes un ingénieur expert en fiabilité de site (SRE) et gestion des quotas d'APIs Cloud.
Votre mission est d'auditer en profondeur les politiques de limitation de débit (rate limiting), les quotas du niveau gratuit (free-tier), et les conditions de service des fournisseurs d'APIs LLM afin d'alimenter et calibrer le module d'alerte de risque d'OpenCode-ModelPool (`src/budget.py`).

---

## 🎯 Problématique Spécifique OpenCode-ModelPool
Le module `src/budget.py` définit un seuil critique d'alerte fixé à **1 000 000 de tokens/mois** pour les agents configurés sur des modèles gratuits (`tier: free_tier`).
Les agents de développement OpenCode opèrent avec les volumes mensuels moyens suivants :
- **`build`** : 1 500 000 tokens entrée / 500 000 tokens sortie (Total: 2M tokens/mois).
- **`plan`** : 800 000 tokens entrée / 200 000 tokens sortie (Total: 1M tokens/mois).
- **`explore`** : 500 000 tokens entrée / 100 000 tokens sortie (Total: 600k tokens/mois).
- **`general`** : 600 000 tokens entrée / 200 000 tokens sortie (Total: 800k tokens/mois).

Lors d'un sprint intensif, une seule requête de l'agent `build` ou `plan` peut injecter entre 30 000 et 80 000 tokens de contexte d'un seul coup.

---

## 🔍 Fournisseurs & Métriques à Auditer

### 1. Google AI Studio (Niveau Gratuit Développeur)
- **Modèles** : Gemini 2.5 Flash, Gemini 2.5 Flash-Lite, Gemini 2.5 Pro.
- **Métriques à vérifier** :
  - Requêtes par Minute (RPM) autorisées.
  - Tokens par Minute (TPM) autorisés.
  - Requêtes par Jour (RPD) autorisées.
  - Politique de rétention des données : les données transmises au niveau gratuit sont-elles utilisées pour l'entraînement ?

### 2. OpenRouter (Modèles avec suffixe `:free`)
- **Modèles** : Catalogue complet des variantes gratuites (ex: `meta-llama/llama-3.3-70b-instruct:free`, `google/gemma-4-26b-a4b-it:free`).
- **Métriques à vérifier** :
  - Limitation par adresse IP ou par compte utilisateur (RPM/RPD).
  - Politique de mise en file d'attente (queue prioritization) lors des pics de charge.
  - Taux d'erreurs 429 constatés et temps moyen d'attente avant rejet.

### 3. Groq Cloud (Free Tier Développeur)
- **Modèles** : Llama 3.3 70B Versatile, Qwen 2.5 Coder 32B.
- **Métriques à vérifier** :
  - Plafonds TPM stricts par minute et par jour.
  - Fenêtres glissantes de calcul du quota.

### 4. Mistral AI (La Plateforme - Free/Trial Tier)
- **Modèles** : Codestral, Mistral Small, Ministral.
- **Métriques à vérifier** :
  - Durée et plafonds de crédits gratuits ou limites de requêtes par minute.

---

## 📦 Livrables Attendus

### Livrable 1 : Matrice Comparative des Quotas (Markdown)
| Fournisseur | Modèle | RPM Max | TPM Max | RPD Max | Confidentialité Données (Entraînement ?) | Risque Blocage pour Agent `build` (Haut/Moyen/Bas) |
|---|---|---|---|---|---|---|

### Livrable 2 : Analyse de Risque Opérationnel pour 1M+ Tokens
- Répondre aux questions suivantes :
  1. Si un agent injecte un prompt de 60 000 tokens en un seul appel, quel fournisseur bloquera instantanément la requête pour dépassement de TPM ?
  2. En cas de blocage HTTP 429, quel en-tête de retour fournit la valeur exacte de réessai (`Retry-After`, `x-ratelimit-reset`) ?
  3. Quels paramètres de backoff exponentiel doivent être configurés pour préserver la fluidité du développement sans saturer les files d'attente ?

### Livrable 3 : Paramètres d'Alerte Recommandés pour `src/budget.py`
Fournir un dictionnaire JSON de configuration synthétisant les seuils de sécurité recommandés :
```json
{
  "free_tier_tpm_ceilings": {
    "google": 1000000,
    "openrouter": 50000,
    "groq": 30000,
    "mistralai": 50000
  },
  "recommended_backoff": {
    "initial_delay_sec": 2.0,
    "max_delay_sec": 60.0,
    "factor": 2.0
  }
}
```
