# Streamlit : mémoire et rétention — 15 octobre 2026

La capture fournie montre « It's using too much memory ». La limite RAM est
confirmée, mais la consommation exacte du serveur et son profil ne sont pas
accessibles dans cette session. L'inventaire disque local n'est pas une mesure
de l'hébergement.

Le paquet main téléchargé depuis Kaotic13700/cqe-tableau-eleves représente
54 874 994 octets décompressés. Le cache .runtime_data vivant, préservé entre les
publications, accumulait les observations et les réponses brutes sans rétention.

## Correction mémoire

L'interface et l'export JSON lisaient toutes les observations MACRO/FED/RATES,
décodaient leurs JSON (notamment les longues listes history_tail), puis
build_macro_context ne conservait que la dernière version par indicateur.
La sélection est désormais effectuée dans SQLite avant le décodage. Le tri
intermédiaire utilise seulement les identifiants de lignes et les dates.
Les séries historiques complètes de la dernière version restent disponibles.
Le filtre available_time <= heure courante précède la sélection de version.
Sur la base initiale extraite du paquet réellement publié : 1 884 captures
MACRO/FED/RATES auparavant décodées, contre 68 après sélection. Cela mesure
le nombre de captures, pas une réduction de RAM de production en pourcentage.

hosted_current_macro.py installe cette lecture partagée dans les deux lecteurs
de l'archive extraite. L'installation vérifie l'ancre exacte et est idempotente.
Elle ne touche à aucune fonction de scénario, de score, de prix ou de graphique.
app_bundle.zip est inchangé. Le lanceur invalide les imports de l'ancienne révision
pour que l'export utilise lui aussi le nouveau lecteur.

## Rétention du cache hébergé uniquement

hosted_cache_retention.py refuse les répertoires autres que .runtime_data ainsi
que les chemins ciblés traversant des liens symboliques. Aucun nettoyage n'est
appliqué au data local de recherche.

| Contenu normalisé | Conservation |
|---|---|
| Spot, perpétuels, ETF, stablecoins | 35 jours (fenêtre actuelle et marge du scénario 30 jours) |
| Chaînes d'options | 8 heures (le calcul hébergé en lit 2) |
| Liquidations, CME, captures d'historique funding | 2 jours |
| Breadth | 3 jours |
| Contexte spot récupéré | 1 jour |
| Macro, Fed, taux | Dernière version par indicateur conservée même ancienne, plus 2 jours de versions récentes |
| Familles inconnues | Conservées |

Réponses brutes : suppression de fichiers journaliers clos responses.jsonl
uniquement, après 35 jours en général, après 2 jours pour les chaînes d'options,
événements de liquidation, captures répétées de funding et historiques macro
déjà normalisés. Les fichiers restants ne sont pas modifiés.

Features historiques et live, modèles, prédictions et résultats de recherche
restent intacts. L'application hébergée n'est plus une archive exhaustive de
réponses brutes ou de toutes les versions normalisées ; c'est volontaire pour
l'usage gratuit demandé. Les suppressions anciennes du cache ne sont pas
récupérables depuis ce cache. Les archives locales n'ont pas été supprimées.

Le worker s'exécute à l'initialisation puis chaque heure, réessaie si une collecte
occupe .refresh.lock, et n'enlève jamais le verrou d'un autre worker. SQLite
protège les transactions contre le listener de liquidations indépendant.
Le travail SQL est borné à 45 secondes. Les pages libérées sont réutilisables ;
un VACUUM borné à 15 secondes les restitue au disque si l'espace temporaire
est suffisant. Sinon la compaction est différée explicitement.

Le diagnostic écrit .runtime_data/hosted_retention_status.json et un message
« Hosted cache maintenance » dans les logs : lignes supprimées par famille,
fichiers/octets bruts retirés, tailles de base et espace disque avant/après.
Ne pas présenter ces compteurs comme des mesures RAM.

## Vérification

Tests dédiés : égalité du contexte macro avant/après sélection, exclusion des
versions futures, lecture rétrospective causale, égalité des entrées de calcul
avant/après purge, conservation des dernières versions macro en cas de source
ancienne, protection des modèles/features/recherche, respect du verrou, refus
des liens symboliques et du data local, compaction réellement mesurée sur une
base synthétique de plus de 10 Mo, idempotence de l'installation sur l'archive
réelle téléchargée.

La preuve d'équivalence de calcul porte sur ces tests et le code inspecté.
Suite complète : 259 tests réussis, 753 avertissements, 12,18 secondes.
Elle ne constitue pas une mesure du pic RAM réel de production. La relance
Streamlit et la sortie de l'écran de saturation devront être vérifiées en ligne.

## État de publication

Publication non effectuée : les API GitHub git/trees et contents refusent
l'écriture avec HTTP 403 « Resource not accessible by integration ». Les droits
du propriétaire sur le dépôt sont bien présents ; ceux de l'intégration restent
insuffisants. Une tentative Git non interactive avec le gestionnaire
d'identifiants existant n'a pas pu authentifier l'envoi. Aucune authentification
interactive ni changement de permission n'a été effectué. L'inspection du
navigateur a également été arrêtée par son contrôle de sécurité d'URL.

Le paquet de reprise contient uniquement le lanceur et les deux modules de
maintenance plus cette documentation. Aucun effacement du cache réel du serveur
ni redémarrage Streamlit n'a été confirmé. Ne pas annoncer un gain de RAM réel
ou un volume supprimé en production à ce stade.
