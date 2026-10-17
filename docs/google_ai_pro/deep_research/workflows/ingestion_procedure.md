# Procédure d'Ingestion : Résultats Gemini Deep Research vers `data/models.json` 🛠️

Ce document décrit le protocole rigoureux et reproductible permettant d'ingérer les données tarifaires et techniques produites par **Gemini Deep Research** dans le catalogue de production [`data/models.json`](../../../data/models.json) d'OpenCode-ModelPool.

---

## 🔒 Principes Directeurs
1. **Intégrité Absolue des Données** : Aucun modèle ne peut entrer dans le catalogue s'il ne passe pas avec succès la validation de `src/selector.py:Model.from_dict`.
2. **Exclusion Stricte des Faux Positifs Non-LLM** : Vérification manuelle et automatisée que les modèles audio/musique (Lyria), TTS, transcription, embeddings purs et générateurs d'images sont exclus.
3. **Zéro Régression** : La suite de tests unitaires complète et la validation des agents (`python3 main.py --validate`) doivent être exécutées avec succès avant validation de l'ingestion.

---

## ⚡ Méthode Recommandée : Script Automatisé

Un assistant interactif dédié prend en charge l'ensemble de la procédure en une seule commande :

```bash
# Mode interactif (détection et sélection du fichier) :
python3 import-deep-research.py

# Ou en passant directement le fichier en argument :
python3 import-deep-research.py mon_fichier_deep_research.json
# ou via la CLI principale :
python3 main.py --import-models mon_fichier_deep_research.json
```

Ce script effectue automatiquement :
1. La détection et validation syntaxique du JSON.
2. Le filtrage pur contre tous les modèles non-LLM (`is_non_llm_model`).
3. La validation stricte du contrat `Model.from_dict`.
4. La création d'une sauvegarde horodatée dans `data/backups/`.
5. La fusion atomique sous verrou inter-processus (`.modelpool.lock`) dans `data/models.json`.
6. Le recalcul immédiat des attributions d'agents et du budget prévisionnel.

---

## 📋 Méthode Manuelle Étape par Étape

### Étape 2 : Filtrage Automatique des Faux Positifs Non-LLM
Assurez-vous qu'aucun modèle audio, image ou embedding n'a été inclus par erreur. Vous pouvez exécuter cette commande de contrôle rapide en Python stdlib :

```bash
python3 -c "
import json, re

with open('/tmp/deep_research_candidates.json') as f:
    candidates = json.load(f)

forbidden = re.compile(r'(lyria|music|tts|whisper|transcribe|audio|embed|imagen|sora|robotics)', re.IGNORECASE)
cleaned = []
for m in candidates:
    if forbidden.search(m['id']):
        print(f'❌ Modèle non-LLM exclu : {m[\"id\"]}')
    else:
        cleaned.append(m)

print(f'✅ Modèles LLM validés : {len(cleaned)} / {len(candidates)}')
with open('/tmp/cleaned_candidates.json', 'w') as f:
    json.dump(cleaned, f, indent=2)
"
```

### Étape 3 : Validation Unitaire contre `src/selector.py:Model`
Avant toute injection, validez chaque modèle candidat contre la logique pure du sélecteur :

```bash
python3 -c "
import json
from src.selector import Model

with open('/tmp/cleaned_candidates.json') as f:
    candidates = json.load(f)

for idx, item in enumerate(candidates):
    try:
        model = Model.from_dict(item, context=f'candidat #{idx}')
    except Exception as e:
        print(f'❌ Erreur de validation sur {item.get(\"id\")}: {e}')
        exit(1)

print('✅ Tous les modèles candidats respectent scrupuleusement le contrat Model.')
"
```

### Étape 4 : Fusion Sécurisée avec Sauvegarde Atomique
1. La fusion s'opère en indexant les modèles par leur identifiant unique (`id`).
2. Une sauvegarde horodatée est automatiquement générée dans `data/backups/`.
3. Script d'application de la fusion :

```bash
python3 -c "
import json, os, time, shutil

models_path = 'data/models.json'
backup_dir = 'data/backups'
os.makedirs(backup_dir, exist_ok=True)

# 1. Backup de sécurité
timestamp = time.strftime('%Y%m%d_%H%M%S')
backup_path = os.path.join(backup_dir, f'models_pre_research_{timestamp}.json')
shutil.copy2(models_path, backup_path)
print(f'📦 Backup créé : {backup_path}')

# 2. Chargement existant
with open(models_path, 'r', encoding='utf-8') as f:
    existing_data = json.load(f)

existing_models = {m['id']: m for m in existing_data.get('models', [])}

# 3. Fusion des candidats
with open('/tmp/cleaned_candidates.json', 'r', encoding='utf-8') as f:
    new_candidates = json.load(f)

added = 0
updated = 0
for cand in new_candidates:
    # Nettoyer les champs hors schéma Model avant persistance dans models.json
    clean_model = {
        'id': cand['id'],
        'provider': cand['provider'],
        'tier': cand['tier'],
        'cost_input_per_m': float(cand['cost_input_per_m']),
        'cost_output_per_m': float(cand['cost_output_per_m']),
        'context_window': int(cand['context_window']),
        'supports_tools': bool(cand['supports_tools']),
        'complexity_score': int(cand['complexity_score']),
        'supports_vision': bool(cand.get('supports_vision', False)),
        'supports_reasoning': bool(cand.get('supports_reasoning', False))
    }
    m_id = clean_model['id']
    if m_id in existing_models:
        updated += 1
    else:
        added += 1
    existing_models[m_id] = clean_model

# 4. Écriture atomique
sorted_models = sorted(existing_models.values(), key=lambda m: m['id'])
out_data = {
    'version': existing_data.get('version', 1),
    'updated_at': time.strftime('%Y-%m-%dT%H:%M:%SZ'),
    'models': sorted_models
}

tmp_path = models_path + '.tmp'
with open(tmp_path, 'w', encoding='utf-8') as f:
    json.dump(out_data, f, indent=2, ensure_ascii=False)
os.replace(tmp_path, models_path)
print(f'✨ Fusion réussie : +{added} ajoutés, ~{updated} mis à jour. Total : {len(sorted_models)} modèles.')
"
```

### Étape 5 : Contrôles de Validation et Non-Régression
Exécutez immédiatement la validation du parc d'agents et les tests unitaires :
```bash
# Validation de l'attribution pour les agents build, plan, explore, general
python3 main.py --validate

# Exécution de l'intégralité des tests unitaires
python3 -m unittest discover tests

# Test d'export de la configuration OpenCode
python3 main.py --export
```

Si l'une des commandes échoue, restaurez immédiatement le fichier de backup généré à l'étape 4.

### Étape 6 : Finalisation & Traçabilité Git
Une fois les tests validés, enregistrez l'évolution du catalogue :
```bash
git add data/models.json
git commit -m "data(models): mise à jour du catalogue via audit Gemini Deep Research"
```
