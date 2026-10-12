# Guide de Développement : ModelScope 🤖

Ce document est le **point d'entrée de référence pour l'agent Antigravity** opérant sur le dépôt. Il garantit la continuité opérationnelle, la cohérence des choix techniques et le respect des conventions établies.

---

## 1. Vue d'Ensemble & Objectif

**ModelScope** attribue automatiquement le modèle LLM optimal à chaque agent d'un parc **OpenCode** en fonction :
1. De contraintes techniques d'aptitude (complexité 1-5, support d'outils, taille de contexte minimale, compatibilité des fournisseurs).
2. De contraintes économiques (gratuité préférée, plafond budgétaire mensuel, détection des risques de quota).
3. D'un mécanisme de **surclassement économique (`fallback`)** en l'absence de correspondance stricte.

---

## 2. Flux de Données & Architecture

```mermaid
flowchart TD
    OR["API Publique OpenRouter"] -->|sync_models_from_openrouter| FET["src/fetcher.py"]
    FET -->|Crée backup| BKP["data/backups/*.json"]
    FET -->|Génère| MJ["data/models.json"]
    
    AR["config/agents_requirements.json"] --> SVC["src/service.py"]
    MJ --> SVC
    SVC --> SEL["src/selector.py"]
    SVC --> BUD["src/budget.py"]
    SVC --> EXP["src/exporter.py"]
    EXP -->|Exporte| OC["config/opencode.json"]
    
    CLI["main.py"] --> SVC
    WEB["src/web.py"] --> SVC
```

---

## 3. Checklist d'Onboarding pour Nouvel Agent

Lorsqu'un nouvel agent prend en main ce projet, il doit :
1. **Consulter les fichiers clés :**
   - [.cursorrules](.cursorrules) : Directives strictes et conventions de code.
   - [config/agents_requirements.json](config/agents_requirements.json) : Exigences déclarées pour les agents.
   - [src/selector.py](src/selector.py) : Cœur logique pur de l'attribution.
2. **Exécuter la suite de tests pour vérifier l'intégrité :**
   ```bash
   python3 -m unittest discover tests
   ```
   *Tous les tests doivent être au vert.*
3. **Tester l'exécution principale :**
   ```bash
   python3 main.py --export
   ```

---

## 4. Composants & Responsabilités

| Module / Fichier | Responsabilité Principale | Contraintes Particulières |
|---|---|---|
| [`src/selector.py`](src/selector.py) | Filtrage, tri, sélection et surclassement | **Fonctions pures uniquement**. Aucun appel I/O, réseau ou HTTP. |
| [`src/fetcher.py`](src/fetcher.py) | Récupération OpenRouter & scoring heuristique | Backup puis écriture atomique ; rétention des sauvegardes horodatées. |
| [`src/budget.py`](src/budget.py) | Calcul des coûts au token & alertes de quotas | Seuil critique free-tier : `1_000_000` tokens/mois. |
| [`src/exporter.py`](src/exporter.py) | Génération du JSON pour OpenCode | Schéma officiel OpenCode strict (`opencode.json`) + rapport d'audit séparé (`modelscope-report.json`). |
| [`src/service.py`](src/service.py) | Chargement, orchestration, export et sync | Seule couche I/O ; verrou pour les écritures concurrentes. |
| [`src/web.py`](src/web.py) | Interface HTTP locale | Bind `127.0.0.1` uniquement ; stdlib ; protections CSRF/Origin ; pas de logique métier. |
| [`main.py`](main.py) | Interface CLI en ligne de commande | Supporte `--sync`, `--export [path]`, `--no-fallback`, `--serve [port]`. |

---

## 5. État Actuel du Projet & Historique des Jalons

- ✅ **Jalon 1 (MVP) :** Structures `Model` et `AgentRequirement`, filtrage des outils et complexité, priorisation du gratuit.
- ✅ **Jalon 2 (Catalogue & Fallback) :** Intégration de modèles légers (scores 1-2), logique de surclassement (`fallback`) et tests de compatibilité.
- ✅ **Jalon 3 (Sync OpenRouter & Backups) :** Téléchargement dynamique via l'API OpenRouter, filtrage des tarifs négatifs, backups horodatés dans `data/backups/`.
- ✅ **Jalon 4 (Export OpenCode) :** Module d'export standardisé générant `config/opencode.json` et `config/modelscope-report.json`.
- ✅ **Jalon 5 (Filtres Avancés) :** `min_context_window`, `allowed_providers`, `excluded_providers`, `force_model`.
- ✅ **Jalon 6 (Simulation Budgétaire) :** Calculs de coût mensuel au token, alertes de quotas free-tier, gestion du `max_monthly_budget`.
- ✅ **Jalon 7 (Interface web locale) :** Service applicatif partagé, serveur `127.0.0.1`, page unique de consultation.
- ✅ **Jalon 8 (Conformité & Durcissement) :** Schéma officiel OpenCode strict (additionalProperties: false), scoring de complexité par jetons délimités, sécurité CSRF/Origin et écritures atomiques.
- ✅ **Jalon 9 (Audit Phase 1 - Intégrité Économique & Durcissement Sécurité) :** Correction du tri `lowest_cost` avec primauté stricte du coût financier et départage déterministe (`model.id`), rejet des tarifs `null` et non finis (`NaN`/`Inf`), protection DNS Rebinding (`Host` check global) et en-têtes de sécurité HTTP (`CSP`, `X-Frame-Options`, `X-Content-Type-Options`), conformité stricte `"tool_call"` dans `Ressources/opencode.json(c)` et réactivation des assertions du test d'export corrompu.

---

## 6. Prochaines Étapes Recommandées (Roadmap)

Si le projet doit continuer d'évoluer, les tâches prioritaires suivantes sont identifiées :
1. **Automatisation de la veille de modèles :** Cron GitHub Actions (ou tâche planifiée) pour mettre à jour `data/models.json` chaque semaine depuis OpenRouter.
2. **Gestion multi-sources :** Permettre d'agréger d'autres sources de modèles (ex: Ollama pour les modèles 100% locaux hors-ligne, AWS Bedrock, etc.).
3. **Pénalité de fiabilité free-tier :** Pondération ou option de désactivation des modèles `:free` pour les agents critiques.

---

## 7. Règle d'Or pour Chaque Intervention

> **Ne proposez jamais de commit sans avoir créé ou mis à jour les tests unitaires correspondants dans `tests/` et sans avoir vérifié que `python3 -m unittest discover tests` s'exécute avec succès.**
