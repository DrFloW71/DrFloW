# Instructions Pour Codex

Scope: `C:\Users\flori\Documents\GitHub\DrFloW` et tous ses sous-dossiers.

## Source De Vérité

- Pour tout travail lié à DrFloW, utiliser uniquement ce dossier.
- Ne pas modifier les anciens dossiers `gemma_weda_assistant` ou `Connecteur Heidi-Weda`.
- Inspecter les fichiers sur disque avant toute modification.
- Préserver les changements locaux non liés.

## Confidentialité GitHub

- Ne jamais versionner d'information personnelle, privée ou patient.
- Les transcriptions, audios, historiques, logs, exports PDF/Word/Excel/CSV, bases locales et secrets doivent rester dans `data/` ou dans un dossier ignoré par Git.
- Avant tout commit ou partage, lancer `python tools/check_private_data.py`.
- Le hook `.githooks/pre-commit` doit rester actif via `git config core.hooksPath .githooks`.
- Si un contrôle signale un doute, ne pas contourner le hook : anonymiser ou déplacer le fichier hors Git.

## Application Python

- `app.py` est l’interface Tkinter principale.
- `config.json` garde les réglages locaux durables.
- `data/`, `.venv/`, `__pycache__/`, les logs et les fichiers audio sont des artefacts locaux ignorés par Git.
- Validations utiles après changement applicatif :
  - `python -m py_compile app.py`
  - `python -m unittest discover -s tests`
  - `python -m json.tool config.json`

## Scripts Tampermonkey

- `tampermonkey/weda_bridge.user.js` est le pont DrFloW-WEDA de l’application.
- `scripts/` contient les userscripts WEDA / Heidi / MadeforMed historiques.
- À chaque modification d’un userscript, incrémenter `@version` et la constante interne de version si elle existe.
- Ne pas renommer les clés Tampermonkey/localStorage existantes sans migration volontaire : cela peut perdre l’état navigateur déjà stocké.
- Validation utile après changement userscript :
  - `node --check chemin\du\script.user.js`

## Points À Préserver

- Raccourcis PageUp / PageDown quand un script les expose.
- Mémorisation et reprise des workflows WEDA.
- Worker WEDA avec hash `#AUTO_HH_WEDA_WORKER=...` dans les scripts qui l’utilisent.
- Insertion dans les champs `contenteditable` WEDA.
- Remplissage des champs structurés uniquement s’ils sont vides.
- Détection AMT / automesure.
- Tags WEDA sans doublon et sans limite artificielle.
- Notifications utiles mais non envahissantes.

## Tests Manuels Minimaux Pour Le Connecteur Principal

Après modification du connecteur Heidi/WEDA principal :

1. Tester PageUp depuis WEDA.
2. Tester PageUp depuis Heidi.
3. Tester PageDown depuis WEDA.
4. Tester PageDown depuis Heidi.
5. Vérifier que la bonne session Heidi reste active.
6. Vérifier insertion de la note dans WEDA.
7. Vérifier constantes et suivis.
8. Vérifier tags sans doublons.
9. Vérifier sauvegarde / retour accueil.
10. Vérifier fermeture worker.
