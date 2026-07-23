# DrFloW

Assistant local de consultation médicale :)

Prototype local Windows pour dicter, transcrire avec `faster-whisper`, envoyer le texte à LM Studio / Gemma, vérifier le résultat et préparer un import manuel contrôlé vers WEDA.

## Lancement

Le raccourci de lancement de DrFloW utilise `lancer_assistant_weda_silencieux.vbs` et n’ouvre normalement que l’interface graphique.

Pour lancer en mode dépannage avec une console visible :

```powershell
cd "C:\Users\flori\Documents\GitHub\DrFloW"
.\lancer_assistant_weda.cmd --debug
```

Le lanceur standard crée l’environnement virtuel et installe les dépendances si nécessaire. En cas d’échec avant l’ouverture de l’interface, le journal de lancement est écrit dans `data\launch.log`.

LM Studio doit exposer l’API locale sur :

```text
http://localhost:1234/v1/chat/completions
```

Le serveur local de l’application démarre avec l’interface sur :

```text
http://127.0.0.1:8765
```

## Sécurité GitHub

Ce dépôt ne doit jamais contenir de donnée personnelle, privée ou patient.

Les fichiers locaux à risque restent ignorés par Git : `data/`, logs, historiques, audios, exports PDF/Word/Excel/CSV, bases locales, fichiers `.env` et clés/secrets.

Avant de publier ou committer, lancer :

```powershell
python tools/check_private_data.py
```

Le hook de pré-commit local lance ce contrôle automatiquement. Pour le réactiver si besoin :

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\install_git_hooks.ps1
```

## Prototype actuel

- Interface Tkinter avec zones WEDA, transcription, Prompt 1, Message 1, Résultat 1, Prompt 2, Message 2, Résultat 2 et logs.
- Interface en thème sombre inspiré Material You, avec tons bleu nuit / bleu marine et accents bleu clair.
- Onglet `Moteur de transcription` pour choisir `faster-whisper`, `Qwen3-ASR` ou `Voxtral`.
- `faster-whisper` reste le moteur stable par défaut et le fallback automatique.
- `faster-whisper` force `language=fr` et `task=transcribe` pour éviter la détection automatique ou une traduction en anglais, notamment avec `distil-large-v3`.
- `Voxtral` peut utiliser un serveur local compatible OpenAI sur `/v1/audio/transcriptions` via le champ `Serveur local`, ou une commande externe locale.
- `Qwen3-ASR` reste expérimental et doit être branché par une commande externe locale qui écrit un JSON de transcription.
- Le champ `Commande externe` accepte `{audio_path}`, `{output_json}`, `{model}`, `{language}`, `{device}` et `{runtime}`.
- Benchmark STT possible sur le dernier audio conservé si l’option `Garder audio benchmark` est activée avant la dictée.
- Cases `Prompt`, `Contexte` et `Transcription` dans les onglets Message pour choisir ce qui compose le message envoyé à LM Studio.
- Bouton `Charger fichier` dans les onglets Message : les PDF et fichiers texte sont lus localement, leur texte extrait est ajouté au message Gemma, ou disponible via `{{attachments}}`.
- Bouton `Envoyer à LM Studio` dans chaque onglet Message pour traiter uniquement le document affiché, même sans audio, à partir du prompt, du contexte, de la transcription ou des fichiers chargés.
- Message LM Studio recalculé automatiquement dès qu’un champ source est modifié.
- Analyse secondaire optionnelle : si `Activer Prompt 2` est coché, l’application lance Prompt 2 après un Résultat 1 valide et conserve Résultat 1 même si Prompt 2 échoue.
- Le message LM Studio distingue la transcription du jour du contexte WEDA, qui correspond aux consultations récentes et données médicales du dossier.
- Taille de fenêtre mémorisée automatiquement après redimensionnement.
- Bandeau permanent de verrou patient : identité du dossier, fraîcheur du contexte et PatDk restent visibles ; un résultat généré pour un autre dossier ne peut pas être préparé pour import WEDA.
- Bouton `Diagnostic DrFloW` pour vérifier localement Python, configuration, micro, STT, LM Studio, serveur, pont WEDA et protections Git, avec rapport anonymisé copiable.
- Annulation des générations LM Studio en cours, progression en temps réel et lecture des réponses en flux quand l’API locale le permet.
- Historique local des versions de prompts, comparaison de versions/résultats et métriques techniques sans texte clinique dans `data/`.
- Réglage graphique de la temporisation avant récupération du contexte WEDA.
- Mode `Connecteur WEDA actif` avec touches de déclenchement/arrêt configurables.
- Dictée segmentée par blocs, transcription en arrière-plan, modèle Whisper actif et micro d’entrée modifiables.
- Mode `Dictée à la volée active` : maintenir la touche configurée (`²` par défaut), relâcher pour transcrire avec Whisper puis coller automatiquement le texte dans le champ actif, avec un sélecteur de modèle séparé (`medium` par défaut).
- Deux démarrages de dictée : `Poursuivre dictée` conserve les champs, `Nouvelle dictée` efface les données de session avant de repartir.
- Gestion locale des prompts dans `prompts.json`.
- Onglet `PDF structurés` pour importer des modèles PDF AcroForm, générer des valeurs JSON avec Gemma, prévisualiser/corriger champ par champ puis exporter une copie remplie après validation humaine.
- Gestion des prompts initiaux Whisper dans `whisper_initial_prompts.json`, avec sélection active depuis l’onglet `Prompt Whisper`.
- Gestion d’une liste d’abréviations dans `abbreviations.csv`, éditable depuis l’onglet `Abréviations`.
- Appel LM Studio compatible OpenAI en HTTP local.
- Historique local optionnel dans `data/history.jsonl`.
- La dernière transcription visible est conservée dans `data/last_transcription.json` à la fermeture normale et restaurée automatiquement au lancement suivant. Effacer la transcription ou démarrer une nouvelle dictée supprime ce brouillon local.
- Serveur local standard library avec `/health`, `/weda/context`, `/weda/latest-result`, `/weda/import-request`, `/weda/import-status`, `/connector/start`, `/connector/stop`, `/connector/status`, `/debug/logs` et `/debug/log`.
- Script Tampermonkey minimal dans `tampermonkey/weda_bridge.user.js`.

## Pont WEDA

Installer `tampermonkey/weda_bridge.user.js` dans Tampermonkey.

Dans WEDA, le bouton flottant permet :

- d’envoyer un contexte patient vers l’application, en lisant les documents/iframes WEDA accessibles et en dépliant l’historique via `Suite WEDA` quand le bouton est présent ;
- d’importer le dernier résultat préparé par l’application dans le champ de consultation WEDA (`ConsultationForm.aspx`, champ `contenteditable`) ou, à défaut, dans le champ actif fiable ;
- de bloquer l’import si le `PatDk` WEDA courant ne correspond pas au patient attaché au résultat.
- de copier les logs Tampermonkey si le serveur local n’est pas joignable.

En mode manuel, l’import nécessite un clic explicite côté WEDA après validation dans l’application.

En mode `Connecteur WEDA actif`, les touches configurées dans l’interface remplacent le couple `PageUp` / `PageDown` du connecteur Heidi :

- déclenchement : depuis l’accueil patient WEDA, démarre une nouvelle dictée et programme la récupération du contexte après le délai configuré ;
- arrêt / envoi : arrête la dictée, capture immédiatement le contexte si l’accueil patient est encore affiché, envoie contexte + transcription + prompt à LM Studio, attend le résultat, ouvre la consultation WEDA, insère le texte puis tente le retour à l’accueil patient.

Le pont mémorise le travail en cours dans `localStorage` pour reprendre après les navigations WEDA. En cas de page ou bouton introuvable, il affiche un badge et laisse un fallback manuel avec logs.

## Transcription médicale progressive Large-v3

La dictée principale utilise par défaut `faster-whisper` avec le modèle complet `large-v3`, CUDA, FP16, français forcé, `beam_size=5` et `temperature=0`. L’audio est capturé en continu puis transcrit dans l’ordre par fenêtres de 30 secondes avec 2 secondes de chevauchement. À l’arrêt, toute fin de consultation encore en mémoire est transcrite, même si elle dure moins de 30 secondes. La répétition textuelle due au chevauchement est retirée par comparaison déterministe des mots, sans rapprochement approximatif des nombres, doses ou latéralités.

L’onglet `Prompt Whisper` contient le prompt médical fixe, un bouton de restauration, les options d’enrichissement WEDA et le lexique permanent local. `Diagnostic Whisper` montre localement le prompt final et les hotwords réellement préparés. Le contexte dynamique est nettoyé, limité à 800 caractères et n’inclut pas l’identité administrative du patient. Si la version installée de `faster-whisper` ne comprend pas `hotwords`, DrFloW le signale puis poursuit avec le prompt dynamique.

L’onglet principal `Transcription` regroupe les deux niveaux dans deux sous-onglets distincts :

- `Transcription brute` conserve la sortie assemblée du moteur, uniquement dédupliquée techniquement ;
- `Transcription corrigée` est éditable et sert aux analyses Gemma lorsqu’elle n’est pas vide ;
- les Résultats 1, 2 et 3 restent les productions Gemma et n’écrasent jamais les deux transcriptions.

Une correction n’est mémorisée qu’après `Comparer les corrections`, puis `Valider explicitement`. Le stockage est local et atomique dans `data/transcription_corrections.json`. Les corrections médicales validées peuvent enrichir les hotwords. Leur application automatique est désactivée par défaut ; lorsqu’elle est activée, elle exige au moins trois validations, une source non ambiguë et exclut négations, nombres, unités critiques et latéralités.

### Procédure de test manuel

1. Démarrer DrFloW sans contexte WEDA et vérifier dans `Moteur de transcription` : `faster-whisper`, `large-v3`, `cuda`, `float16`.
2. Enregistrer une consultation de plus de deux minutes et confirmer que du texte apparaît environ toutes les 28 secondes, dans l’ordre, sans phrase répétée aux jonctions.
3. Arrêter au milieu d’une fenêtre et vérifier que la dernière phrase apparaît après la fin de la file de transcription.
4. Charger un contexte WEDA contenant plusieurs médicaments, ouvrir `Prompt Whisper` puis `Diagnostic Whisper`, et vérifier le contexte nettoyé ainsi que les hotwords.
5. Modifier et enregistrer le prompt Whisper, redémarrer l’application et vérifier sa persistance ; utiliser `Restaurer le prompt par défaut` pour revenir au texte livré.
6. Dans `Transcription` > `Transcription corrigée`, corriger volontairement un terme, comparer puis valider explicitement. Vérifier la création de `data/transcription_corrections.json`.
7. Répéter la même correction et vérifier que `validation_count` augmente au lieu de créer un doublon.
8. Vérifier enfin que `Transcription` > `Transcription brute` est restée inchangée et que Prompts/Résultats 1 et 2 fonctionnent comme avant.

## Debug

Les logs applicatifs sont visibles dans l’onglet `Logs` de l’application et enregistrés localement dans :

```text
data/debug.log.jsonl
```

Pour la dictée, choisir le bon périphérique avec le menu `Micro` avant de démarrer. Les segments vides ou silencieux restent hors de l’onglet `Transcription` et ne sont pas envoyés à LM Studio. Le niveau micro (`RMS` / `peak`) est affiché dans la barre de statut et les logs `segment_transcribed` indiquent aussi `audio_stats` (`duration_seconds`, `rms`, `peak`, `dbfs`) et `empty_reason`. Si `rms` et `peak` restent à `0`, Windows ou `sounddevice` enregistre probablement le mauvais micro ou du silence. Si un signal est détecté mais que le texte reste vide, l’application retente automatiquement le segment sans VAD.

La `Dictée à la volée` utilise uniquement Whisper : elle ne passe pas par LM Studio, ne modifie pas la transcription principale et n’applique pas les abréviations. Elle possède son propre choix de modèle, précharge ce modèle en arrière-plan quand l’option est active, transcrit d’abord depuis le buffer audio en mémoire, puis retombe sur l’ancien fichier WAV temporaire si la version locale de `faster-whisper` l’exige. Le module `keyboard` écoute la touche globale, la bloque pendant l’appui, copie le texte obtenu puis envoie `Ctrl+V` à la fenêtre active. Le collage global peut être refusé par Windows si la fenêtre cible est lancée avec des droits administrateur plus élevés que l’assistant.

L’onglet `Prompt Whisper` permet de créer plusieurs `initial_prompt` Whisper. Le prompt sélectionné est activé immédiatement et utilisé pour les segments suivants ; le bouton `Activer` sauvegarde le texte affiché comme prompt actif.

L’onglet `Abréviations` n’est pas utilisé comme prompt Whisper ni envoyé à LM Studio. Whisper reste chargé de produire une transcription fidèle de l’oral. La liste `find,replace` sert en post-traitement local : après chaque réponse LM Studio, l’application remplace les expressions exactes trouvées dans le résultat final. Le bouton `Appliquer substitutions sûres` peut aussi remplacer manuellement des expressions exactes dans la transcription après confirmation.

Le pont Tampermonkey envoie aussi ses événements au serveur local. Si l’import ne trouve pas le champ WEDA, ouvrir la page de consultation du patient puis cliquer `Importer résultat`. Le script cible maintenant en priorité le champ de consultation WEDA, mémorise aussi le dernier champ éditable fiable et cherche dans les iframes accessibles.

Le réglage `Délai contexte (s)` dans l’application contrôle l’attente entre le clic `Envoyer contexte` dans WEDA et la lecture effective du contexte. La valeur par défaut est `60` secondes, comme le module contexte du connecteur Heidi-WEDA.

Le contexte WEDA reste valide sans limite de durée. L’import exige toujours un PatDk identique à celui capturé au moment de la génération : un changement de dossier patient verrouille donc les anciens résultats, indépendamment de leur ancienneté.

Le contexte WEDA n’est pas une transcription et ne doit pas interférer avec la fidélité de l’oral. Il sert après transcription, avec la transcription du jour, à préciser des informations, lever des ambiguïtés et rédiger des documents médicaux cohérents à partir du dossier.

## Analyse secondaire / Prompt 2

L’onglet `Prompt 2` permet d’activer une deuxième analyse LM Studio optionnelle. Le menu affiche les prompts `secondary` et `generic`; les anciens prompts sans `prompt_type` restent compatibles comme `generic`. Le prompt secondaire par défaut s’appelle `Analyse secondaire`.

Le Message 2 peut utiliser notamment `{{transcription}}`, `{{weda_context}}`, `{{prompt_1_name}}`, `{{prompt_1_content}}`, `{{result_1}}` et `{{lmstudio_result}}` ; pour Prompt 2, `{{lmstudio_result}}` est un alias de `{{result_1}}`.

L’historique local ajoute `prompt_1_*`, `message_sent_1`, `result_1`, `prompt_2_*`, `message_sent_2`, `result_2` et `prompt_2_status`. Le bouton `Importer Résultat 2 dans WEDA` prépare seulement un import manuel via le pont WEDA, avec validation explicite côté WEDA.

## PDF structurés

L’onglet `PDF structurés` gère uniquement les PDF avec vrais champs de formulaire AcroForm. Les PDF scannés ou plats sans champ affichent un message d’échec et ne sont pas remplis en V1.

Les modèles sont stockés localement dans `data/pdf_templates/` et les PDF finaux exportés dans `data/pdf_outputs/`. Gemma ne produit jamais le PDF final : elle propose seulement un JSON strict, validé et affiché champ par champ. L’utilisateur doit vérifier/corriger les valeurs puis cliquer explicitement sur `Remplir / exporter PDF`; le PDF modèle original reste intact.

Le menu `Source PDF` choisit la source principale exposée au prompt PDF via `{{lmstudio_result}}` : contexte + transcription, transcription seule, Résultat 1, Résultat 2, ou Résultat 1 + Résultat 2. Le prompt PDF est éditable directement dans l’onglet `PDF structurés` et peut rester très court : les libellés/descriptions des champs PDF guident le remplissage.

Pour les formulaires longs, l’appel PDF demande davantage de tokens à LM Studio via `pdf.max_tokens` (`8192` par défaut). Si Gemma renvoie quand même un JSON coupé en cours de génération, l’application récupère les champs JSON complets déjà reçus, marque le résultat comme partiel, et laisse les champs manquants absents. Les champs absents ou vides ne sont pas écrits dans le PDF final.
