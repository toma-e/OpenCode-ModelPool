# Directives de Développement : OpenCode-ModelPool 🤖

Ce dépôt est piloté par l'agent **Antigravity**. Pour toute information détaillée sur l'architecture, la suite de tests, la conformité OpenCode et la feuille de route, veuillez vous référer au document canonique :

👉 **[AGENTS.md](AGENTS.md)**

## Règle d'or
Avant de valider ou proposer un commit :
```bash
python3 -m unittest discover tests
python3 main.py --validate
```
Tous les tests doivent obligatoirement réussir.
