# Canevas pour Audio Overview (Podcast 2 Voix) dans NotebookLM 🎙️

NotebookLM dispose d'une fonctionnalité de génération de résumés audio interactifs (**Audio Overview**), simulant un dialogue captivant entre deux experts en IA.

Ce canevas fournit la trame éditoriale, le cadrage technique et les consignes d'orientation à insérer dans la zone de personnalisation de l'Audio Overview (*Customize Audio Overview*) pour générer un épisode de revue technique de haute volée dédié à **OpenCode-ModelPool**.

---

## 🎭 Personas des Deux Intervenants

- **Intervenant 1 (Alex - Architecte Système & Lead Dev)** :
  - Profil : Développeur rigoureux, passionné par les architectures logicielles pures, l'absence de dépendances externes et la rapidité d'exécution (la suite de tests qui tourne en 0,16s est sa fierté).
  - Style : Précis, méthodique, valorisant l'élégance de la conception et la résilience du code.
- **Intervenant 2 (Sam - Ingénieur FinOps & Infrastructure IA)** :
  - Profil : Analyste financier et spécialiste des quotas de calcul, obsédé par l'optimisation des coûts au million de tokens, la détection des plafonds de débit et l'utilisation judicieuse des niveaux gratuits.
  - Style : Dynamique, pragmatique, friand d'analogies concrètes et d'astuces économiques.

---

## 📝 Consigne de Personnalisation (Prompt de Guidage)

*Copiez ce texte dans le champ de personnalisation de l'Audio Overview de NotebookLM :*

```text
Générez une discussion technique approfondie, rythmée et accessible entre deux ingénieurs chevronnés (Alex et Sam) analysant l'architecture et les arbitrages du projet OpenCode-ModelPool.

La conversation doit impérativement articuler les 4 temps forts suivants :

1. L'Anti-Pattern du Modèle Unique :
   Pourquoi affecter un modèle frontière ultra-coûteux (comme Claude 3.5 Sonnet ou GPT-4o) à chaque agent d'un parc de développement est une aberration économique et opérationnelle. Mettre en contraste les besoins colossaux de l'agent 'build' (outils d'écriture, refactoring complexe) avec les besoins modestes du sous-agent 'explore' (qui a juste besoin d'être rapide, concis et gratuit).

2. L'Élégance d'un Cœur Purement Fonctionnel :
   Souligner le choix architectural fort de 'src/selector.py' : un moteur de sélection 100% pur, sans appel réseau ni lecture disque, reposant uniquement sur la bibliothèque standard Python. Raconter avec enthousiasme comment l'isolation des fonctions pures et l'élimination des verrous bloquants permettent d'exécuter l'ensemble des 140+ tests en moins de 0,2 seconde.

3. La Puissance du Routage Hybride Multi-Fournisseurs :
   Décrire comment le projet réconcilie trois mondes : le local souverain avec Ollama (port 11434), les APIs directes à ultra-faible latence (Google AI Studio, Groq, Mistral, Cerebras) avec vérification dynamique des clés réelles, et le filet de sécurité universel via OpenRouter.

4. Le Surclassement Économique (Fallback) et la Gestion des Quotas :
   Expliquer comment le système garantit qu'aucun agent ne se retrouve sans modèle si son créneau exact est indisponible, en le surclassant intelligemment vers le modèle compatible le plus économique, tout en avertissant le développeur s'il risque de saturer le plafond critique de 1 000 000 tokens/mois sur les tiers gratuits.

Le ton doit être complice, professionnel, rythmé par des échanges stimulants, sans jargon superflu mais avec une haute rigueur technique.
```

---

## 🎧 Durée et Format Attendus
- **Durée estimée** : 10 à 15 minutes.
- **Format d'export** : Fichier audio (M4A / WAV) téléchargeable directement depuis l'interface NotebookLM.
- **Utilisation** : Onboarding accéléré des nouveaux contributeurs, présentation aux parties prenantes et revue d'étape lors des rétrospectives d'architecture.
