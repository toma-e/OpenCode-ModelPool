# Lanceurs pour l'Interface Web Locale

Ce dossier contient des scripts pour démarrer et arrêter facilement l'interface web locale de ModelScope.

## Windows (via WSL)

### Démarrer le serveur

**Option 1 : Script Batch**
Double-cliquez sur `start-web.bat` ou exécutez dans un terminal Windows :
```cmd
start-web.bat
```

**Option 2 : Script PowerShell**
Exécutez dans PowerShell :
```powershell
.\start-web.ps1
```

Ces scripts effectuent :
- La détection automatique si le serveur est déjà actif (pour éviter les doublons).
- Le lancement propre du serveur dans WSL sur `http://127.0.0.1:8765/`.
- L'ouverture automatique du navigateur Windows par défaut dès que le serveur est prêt.
- L'affichage des requêtes HTTP en direct dans la console.
- L'arrêt propre en fermant la console ou avec `Ctrl+C`.

### Arrêter le serveur

Si le serveur a été lancé dans une console distincte ou en arrière-plan :

**Option 1 : Script Batch**
Double-cliquez sur `stop-web.bat` ou exécutez :
```cmd
stop-web.bat
```

**Option 2 : Script PowerShell**
Exécutez dans PowerShell :
```powershell
.\stop-web.ps1
```

---

## Linux / WSL Direct

### Démarrer le serveur
Dans un terminal bash sous Linux ou WSL :
```bash
./start-web.sh
```

### Arrêter le serveur
Dans un autre terminal :
```bash
./stop-web.sh
```
Ou simplement `Ctrl+C` dans le terminal où tourne `start-web.sh`.

---

## Dépannage

### Le serveur ne démarre pas
- Vérifiez que Python 3 est installé dans WSL : `python3 --version`
- Vérifiez que le port 8765 n'est pas déjà occupé : `curl http://127.0.0.1:8765/`
- Consultez les logs ou lancez manuellement : `python3 main.py --serve 8765`

### Le navigateur ne s'ouvre pas
- Ouvrez manuellement votre navigateur sur [http://127.0.0.1:8765/](http://127.0.0.1:8765/)
- Vérifiez qu'aucun pare-feu ne bloque les connexions locales loopback sur le port 8765.

### Erreur "WSL n'est pas disponible"
- Assurez-vous que WSL 2 est installé et actif sur Windows (`wsl --status`).
