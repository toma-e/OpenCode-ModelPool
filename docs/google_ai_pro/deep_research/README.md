# Gemini Deep Research : Guide Opérationnel & Points de Contact 🔍

## 1. Rôle et Mission

Dans l'architecture OpenCode-ModelPool, **Gemini Deep Research** agit comme le moteur d'intelligence de marché autonome. Son rôle est de parcourir le web, d'examiner la documentation officielle des fournisseurs (Google AI Studio, OpenAI, Anthropic, Mistral, Groq, Cerebras, OpenRouter), et d'en extraire des données factuelles vérifiées sans perturber le cœur logiciel Python (stdlib-only).

### Domaines d'Intervention :
1. **Benchmark de Tarification Multi-Fournisseurs** : Extraction exhaustive des coûts d'entrée et de sortie convertis en **$/1M tokens**, fenêtres de contexte et capacités techniques.
2. **Surveillance des Endpoints et Dépréciations** : Détection des migrations d'API, fermetures de modèles et ouvertures de nouvelles versions bêta ou stables.
3. **Surveillance des Quotas et Rate Limits** : Audit des plafonds du niveau gratuit (`RPM`, `TPM`, `RPD`) et analyse des risques de saturation pour les parcs d'agents.

---

## 2. Points de Contact & Interfaces

Deep Research communique avec OpenCode-ModelPool via des artefacts strictement définis :

| Point de Contact | Description | Type / Emplacement |
|---|---|---|
| **Schéma de Sortie** | Validation des attributs du modèle LLM | [`schemas/benchmark_output.schema.json`](schemas/benchmark_output.schema.json) |
| **Cible d'Intégration** | Catalogue persistant de modèles | [`data/models.json`](../../../data/models.json) |
| **Contrat Logiciel** | Classe de données pure avec validation stricte | `src/selector.py:Model.from_dict` |
| **Procédure d'Ingestion** | Protocole pas-à-pas de vérification et fusion | [`workflows/ingestion_procedure.md`](workflows/ingestion_procedure.md) |

---

## 3. Modalités d'Exécution

### Option A : Interface Gemini Advanced / Google AI Pro (Web)
1. Ouvrez Gemini Advanced avec le mode **Deep Research** activé.
2. Copiez l'un des prompts prêts à l'emploi du dossier `prompts/`.
3. Laissez l'agent exécuter ses recherches multi-étapes (généralement 5 à 15 minutes).
4. Exportez le rapport Markdown et le bloc JSON final.

### Option B : API Google AI Studio / Vertex AI
Utilisez le modèle de recherche autonome (ex: `deep-research-preview-04-2026` détecté dans `data/provider_access.json`) pour automatiser le cycle de recherche via script de veille externe.

---

## 4. Prompts Disponibles

- [`prompts/pricing_benchmark.md`](prompts/pricing_benchmark.md) : Benchmark tarifaire complet ($/1M tokens, LLMs code/texte uniquement, exclusion audio/multimédia pur).
- [`prompts/provider_updates.md`](prompts/provider_updates.md) : Veille des versions d'API, modifications de contexte et calendrier de fin de vie (EOL).
- [`prompts/token_monitoring.md`](prompts/token_monitoring.md) : Suivi des quotas free-tier, plafonds de requêtes et conditions d'utilisation.
