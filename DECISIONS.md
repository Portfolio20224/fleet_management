# Fiche de décisions — corrections Fleet Manager

Sur les 100 points du tableau, **80 ont été appliqués tels quels**, 11 autrement que prévu, 7 pas du tout. Pour 2 points, il n'y avait rien à faire : #35 (déconnexion en POST, déjà correcte) et #94 (`TIME_ZONE` déjà réglé sur `Africa/Abidjan`).
Vérification : 24 tests automatisés passent (`python manage.py test fleet`), chaque page s'affiche pour chaque rôle autorisé et renvoie 403 pour les autres, et `check --deploy` ne signale plus que les options HSTS facultatives.

## 1. Corrections non appliquées

| # | Proposition | Raison |
|---|---|---|
| 22 | Montants en `DecimalField` | Le FCFA n'a pas de centimes en usage. La recommandation elle-même prévoyait l'exception « sauf si FCFA entier assumé ». Les montants restent des entiers, et un commentaire l'indique dans le modèle. |
| 49 | `gettext_lazy("FCFA")` | « FCFA » est un code de devise, pas un texte à traduire, et l'application n'existe qu'en français. Il est défini dans une constante `DEVISE` dans `filters.py`. |
| 57 | Préfixe d'URL `fleet/` | L'application occupe tout le site : l'accueil deviendrait `/fleet/` et toutes les URL documentées changeraient, pour aucun gain. Un commentaire l'explique dans `urls.py`. |
| 58 | `MEDIA_URL = "/media/"` | Ce n'est pas un bug : depuis Django 3.1, un `STATIC_URL`/`MEDIA_URL` relatif est géré, et c'est la valeur par défaut de `startproject`. Rien n'a été changé. |
| 84 | `{% load static %}` dans `base.html` | La correction était conditionnelle (« dès qu'un asset local est utilisé ») et il n'y a aucun asset local. |
| 93 | Fallback local des CDN | Il faudrait embarquer des copies de Bootstrap, Chart.js et Leaflet dans le projet, ce qui n'est pas fait aujourd'hui. Un fallback vers des fichiers absents ne servirait à rien. À faire en même temps que le passage aux assets locaux. |
| 98 | `pip freeze > requirements.txt` | Le fichier existait déjà. `pip freeze` y aurait déversé tous les paquets du poste. On ajoute seulement `Pillow`, devenu nécessaire. |

## 2. Corrections appliquées autrement

| # | Proposition | Ce qui a été fait, et pourquoi |
|---|---|---|
| 2 | `j_ct = … else 9999` | **Le plantage annoncé n'existe pas** : le `{% if %}` de Django renvoie *faux* sur `None < 0` au lieu de lever `TypeError` (vérifié). Le vrai défaut était l'affichage de « None ». La valeur 9999 aurait affiché « 9999 jours ». Le gabarit affiche maintenant « — » quand la date manque. |
| 11, 92 | `{% if debug %}` | La variable `debug` de Django n'est remplie que si l'IP du client figure dans `INTERNAL_IPS`. En pratique elle serait vide et cacherait les comptes même en développement. On a ajouté un context processor qui expose `show_demo_accounts` (réglable via `FLEET_SHOW_DEMO_ACCOUNTS`, par défaut égal à DEBUG) et `show_dev_notes`. |
| 12 | `DEBUG=False` | Avec `DEBUG=False` par défaut, `runserver` ne sert plus les fichiers media et la procédure du README ne marche plus. Tout se lit dans des variables d'environnement : le **mode développement est le défaut**, la **production exige** `DJANGO_SECRET_KEY` (sinon le démarrage échoue) et active automatiquement les réglages `SECURE_*` (#96). |
| 1 | `{% load filters %}` dans technique | Ajouté. En plus, la vue construit maintenant les colonnes du kanban (libellé, étape suivante, pannes), ce qui simplifie le gabarit. Les filtres `get_item` et `next_etape` restent disponibles et corrigés (#45-46). |
| 39, 89 | Accents dans les **valeurs** en base | Seuls les **libellés** prennent les accents (`("En conge", "En congé")`). Les codes stockés restent en ASCII et les gabarits passent par `get_…_display`. On évite ainsi une migration de données et des codes accentués dans le code et le JavaScript. Le risque d'écart entre vues et base disparaît. |
| 36, 38 | « Dates anglaises / ISO » | Le constat était faux : avec `fr-fr`, Django affiche déjà « 22 novembre 2026 ». `|date:"d/m/Y"` est tout de même appliqué partout, parce que c'est plus compact dans les tableaux. |
| 60 | `ratio` à clarifier | La formule `(R-D)/R` est conservée et nommée « marge nette », avec un libellé explicatif. La barre passe en rouge si le solde est négatif. |
| 26 | `ImageField` « si vrai upload » | La condition n'était pas remplie (il n'y a pas d'upload de photo chauffeur dans l'interface). `ImageField` est appliqué quand même, parce que l'admin permet l'upload et que Pillow sert déjà à vérifier les images (#6). |

## 3. Choix d'implémentation à connaître

- **#6 Uploads** : limite de 5 Mo et type `image/*`, plus une **vérification du contenu réel avec Pillow**, car le type MIME est déclaré par le navigateur et peut être falsifié. La règle s'applique aussi à la photo de panne.
- **#9 Numéros d'ordre** : contrainte unique `(date, num_ordre)`, `select_for_update()` et jusqu'à 3 essais en cas de collision. SQLite ignore `select_for_update` : sur SQLite, c'est la contrainte qui garantit l'unicité.
- **#29 403** : page `403.html` avec un lien de retour. Les 403/404 ne sont plus journalisés avec leur traceback ; les erreurs 500 le restent.
- **#30 CBV** : un `RoleRequiredMixin` a été ajouté, mais l'application n'a aucune vue-classe aujourd'hui.
- **#32 / #77 Clôture** : cases à cocher avec « Tout sélectionner ». Un percepteur ne clôture **que ses propres recettes** ; la DG peut tout clôturer. Le tableau et les KPI du jour restent globaux. *Choix métier à valider.*
- **#75 Panne** : un chauffeur ne déclare une panne que sur **son véhicule attribué** (contrôlé côté serveur). Sans véhicule attribué, le formulaire est remplacé par un message. La DG peut choisir n'importe quel véhicule. *Choix métier à valider.*
- **#44 Injection CSV** : seules les chaînes sont préfixées par `'`. Les nombres (montants négatifs compris) restent des nombres, sinon `-2000` deviendrait du texte dans Excel.
- **#43 Export** : streaming, plus `select_related` sur les clés étrangères. L'ancien export faisait une requête par ligne et par clé étrangère.
- **#56 `app_name = "fleet"`** : tous les `{% url %}`, les `redirect()` et `LOGIN_REDIRECT_URL` ont été adaptés.
- **#88 `addresse` → `adresse`** : sans coût, puisque le projet ne contenait aucune migration.

## 4. Changements hors tableau

- **Migration initiale fournie** (`0001_initial.py`). Si une base locale existe déjà, supprimez `db.sqlite3` et vos anciennes migrations, puis lancez `migrate` et `seed_demo`.
- **Séparateur CSV `;`** : Excel en français ouvre un CSV séparé par des virgules sur une seule colonne. Les dates du rapport DG sont au format `jj/mm/aaaa`.
- **Accents corrigés dans les messages des vues et les alertes DG**, en plus des gabarits.
- **Page de connexion** : un utilisateur déjà connecté est redirigé vers l'accueil, et le nom saisi est conservé après une erreur.
- **Validations supplémentaires en RH** : nom et prénom obligatoires, permis dans {B, C, D, E}, type de congé dans la liste. Une décision ne s'applique qu'à un congé « En attente ».
- Ajout de `.gitignore` et `.env.example` (#99) ; le README a été mis à jour (#100).

## 5. Points laissés en l'état, à décider

- `Attribution.chauffeur/vehicule` et `Panne.vehicule` restent en `CASCADE` : supprimer un véhicule efface encore ses attributions et ses pannes. C'est cohérent avec #24 (« garder l'historique ») de passer en `PROTECT`, mais ce n'était pas demandé.
- Approuver un congé ne change pas le statut du chauffeur (« En congé »).
- L'e-mail généré à l'ajout d'un chauffeur (`prenom.nom@fleet.local`) peut entrer en collision pour deux homonymes.

## 6. Évolution — logique métier de la saisie rapide (22/11/2026)

Demande : le véhicule attribué se sélectionne automatiquement, une seule recette par chauffeur sur 12 heures, la liste des chauffeurs est filtrée par attribution, et la validation se fait par double clic.

- **Horodatage** : `Recette` n'avait qu'une date. Un champ `saisie_le` (date et heure) a été ajouté, avec la migration `0002`. Les recettes déjà en base sont placées à minuit de leur date, pour ne pas bloquer tous les chauffeurs pendant 12 h juste après la migration.
- **Règle des 12 h, contrôlée côté serveur** : elle s'applique même si le JavaScript est contourné. La ligne du chauffeur est verrouillée pendant la vérification, pour que deux percepteurs ne puissent pas valider en même temps. La fenêtre est glissante : une recette à 06:30 bloque jusqu'à 18:30. Le message d'erreur indique l'heure, le numéro et le percepteur de la recette existante. La règle vaut aussi pour la DG ; une correction exceptionnelle passe par l'admin.
- **Liste filtrée** : seuls les chauffeurs actifs qui ont une attribution en cours apparaissent. Ceux qui ont déjà une recette dans les 12 h restent **visibles mais grisés**, avec l'heure à partir de laquelle une saisie redevient possible. Le percepteur voit ainsi pourquoi un chauffeur n'est pas sélectionnable.
- **Véhicule** : il n'est plus choisi librement. Le serveur refuse tout véhicule qui n'est pas attribué au chauffeur. Si un chauffeur a plusieurs véhicules attribués, le menu ne propose que les siens.
- **Situation du véhicule** : l'ancien filtre « En service » a été remplacé par l'attribution, qui fait foi. Un véhicule attribué mais en panne reste saisissable, avec sa situation affichée à côté de la plaque. *À durcir si le métier l'exige.*
- **Double clic** : le premier clic arme le bouton (« Cliquez encore pour confirmer »), le second dans les 1,5 s envoie le formulaire, puis le bouton se désactive. Cette mise en œuvre marche aussi au double appui sur mobile, où l'événement `dblclick` natif n'est pas fiable. La touche Entrée suit la même règle. Sans JavaScript, un simple clic envoie, mais les règles serveur restent appliquées.
- **Données de démo** : au plus une recette par chauffeur et par jour, le matin, avec le véhicule attribué. Aujourd'hui, 2 chauffeurs ont déjà versé et sont grisés ; les autres sont disponibles.

## 7. Évolution — pointage RH, formulaires et statistiques (26/11/2026)

### Pointage par la RH
- Le chauffeur ne peut plus se pointer : son espace affiche son pointage du jour en lecture seule. La RH pointe dans un nouvel onglet **« Pointage du jour »** : une ligne par chauffeur actif avec les boutons Arrivée, Départ et Absent, et une heure facultative (vide = maintenant, heure future refusée).
- Une arrivée après 07:30 est comptée en retard (`FLEET_HEURE_RETARD`). Le départ doit suivre l'arrivée. Une absence peut être corrigée en arrivée. Un chauffeur en **congé approuvé** n'est pas pointable. Les jours passés se corrigent dans l'admin.
- **Modèle** : la présence est rattachée au **chauffeur**, et non plus au compte utilisateur, pour pouvoir pointer les chauffeurs qui n'ont pas de compte. On enregistre qui a pointé (`pointe_par`), avec une présence au plus par chauffeur et par jour. La migration `0003` rattache les anciens pointages de comptes chauffeurs à leur fiche ; ceux du personnel non chauffeur sont conservés sans rattachement.

### Formulaires ajoutés
- **DG — Ajouter un véhicule** : plaque (unique, mise en majuscules), marque et modèle obligatoires. La **date d'acquisition est obligatoire**, car elle alimente l'âge du parc. Le véhicule est créé « En service », sans position sur la carte.
- **Trésorier — Ajouter une dépense** : date (pas dans le futur), catégorie, montant (> 0), commentaire (nouveau champ). J'ai ajouté le **type** (Opérationnelle par défaut), sinon les charges fixes saisies fausseraient le graphique « par type ». La catégorie propose les catégories existantes et reprend leur orthographe (« carburant » → « Carburant »).
- **RH — Ajouter un chauffeur** : l'**expiration du permis** est ajoutée et obligatoire, car elle alimente les alertes DG. La **date de naissance** est ajoutée aussi, car la pyramide des âges en a besoin ; elle doit indiquer au moins 18 ans.

### Statistiques
- **Fiche chauffeur** (RH : onglet « Statistiques chauffeur », puis choix du chauffeur ; chauffeur : « Mes statistiques », pour lui seul) : indicateurs du mois courant et trois courbes sur 12 mois.
  - *Jour travaillé* = pointage « Présent » ou « Retard ».
  - *Écart de recette* = **versé inférieur au fixe** (un versement supérieur n'est pas un écart), avec le montant manquant du mois.
  - *Panne* = panne dont le chauffeur est le déclarant.
- **Trois graphiques séparés** plutôt qu'un seul : les jours (~25 par mois) écraseraient les pannes (0 à 2) sur un axe commun. Les lignes sont droites, sans lissage qui dépasserait les valeurs réelles. Le dernier mois est marqué « (en cours) ». Un tableau des données accompagne chaque série.
- **Âges des chauffeurs** (RH, onglet « Pyramide des âges ») : répartition par tranche, âge moyen et médian, départs à la retraite sous 12, 24 et 36 mois, liste des départs à moins de 5 ans. Pour juger d'un recrutement, l'onglet montre aussi la **capacité** : véhicules en service sans chauffeur, chauffeurs actifs sans véhicule.
- **Âge du parc** (DG) : âge calculé depuis la date d'acquisition, répartition par tranche, âge moyen, plus ancien, véhicules **à renouveler** et ceux qui **atteindront le seuil sous 12 mois** (achats à budgéter). Le kilométrage est affiché à côté pour nuancer.

### Hypothèses à confirmer
- **Âge de retraite : 60 ans** (`FLEET_AGE_RETRAITE`) et **seuil de renouvellement : 8 ans** (`FLEET_AGE_RENOUVELLEMENT_VEHICULE`). Ce sont des paramètres par défaut, pas des valeurs vérifiées. À ajuster selon la réglementation, la convention collective et la politique d'achat.

### Données de démo
- Un an de pointages RH (repos le dimanche, assiduité variable), des recettes uniquement pour les chauffeurs présents ce jour-là, des pannes et dépenses réparties sur l'année, et des dates de naissance et d'acquisition plus étalées pour que les âges soient parlants. Aujourd'hui, 2 chauffeurs sont déjà pointés ; les autres restent à pointer.

## 8. Évolution — passage au franc congolais et contexte RDC (26/11/2026)

Cette section remplace les mentions du FCFA et d'Abidjan dans les sections précédentes (#22, #49, #94).

- **Monnaie** : les montants s'affichent en **FC** (franc congolais, code CDF). Le filtre `fcfa` est renommé `monnaie`, et le symbole vient d'un réglage (`FLEET_DEVISE`) au lieu d'être écrit en dur. Les montants restent des **entiers** : les centimes du franc congolais ne sont pas utilisés en pratique.
- **Montants par défaut** : convertis au taux d'environ **4 FC pour 1 FCFA** (cours fin 2026). Le montant fixe journalier pré-rempli passe de 25 000 FCFA à **100 000 FC**, et les montants de démo sont multipliés par 4. *Le montant réel est à fixer par la direction (`FLEET_MONTANT_FIXE_DEFAUT`).*
- **Données déjà saisies** : rien n'est converti automatiquement. La commande `convertir_monnaie --taux <taux>` montre d'abord un aperçu ; il faut ajouter `--appliquer` pour écrire en base. Utile seulement si une base contient de vrais montants en FCFA.
- **Âge de retraite : 65 ans par défaut** (au lieu de 60), selon la loi RDC n° 16/009 du 15 juillet 2016. Les tranches d'âge ont été alignées (« 55–64 », « 65 ans et + »).
- **Fuseau horaire** : `Africa/Kinshasa` (UTC+1). Le pointage et la règle des 12 h suivent l'heure de Kinshasa. **Carte** centrée sur Kinshasa (Gombe).
- **Données de démo** : noms congolais pour les chauffeurs et le personnel, téléphones au format +243, adresses dans des communes de Kinshasa, plaques au format RDC (4 chiffres + 2 lettres, ex. `4821AB`), catégories de dépenses accentuées. Deux chauffeurs sont proches de la retraite pour illustrer la pyramide des âges.
- **E-mails générés** : les accents et apostrophes sont retirés (« Héritier » → `heritier`), pour que les adresses restent valides avec les prénoms congolais.
- **Identifiants de connexion inchangés** (`dg`, `finance`, `rh`, `tech`, `per1..3`, `chauf1..3`) : seuls les noms affichés changent.

## 9. Évolution — comptes et mots de passe (26/11/2026)

- **Page « Changer mon mot de passe »** (`/mot-de-passe/`), accessible à tous via le bouton « Mot de passe » de la barre du haut. Elle applique les règles de sécurité de Django : au moins 8 caractères, pas uniquement des chiffres, pas trop courant, pas trop proche du nom. La session reste ouverte après le changement.
- **Création des comptes par la RH** : nouvel onglet « Comptes » dans l'espace RH, qui permet de créer un compte, de générer un nouveau mot de passe, et de désactiver ou réactiver un compte.
  - **Chauffeur** : on choisit sa fiche ; le nom et le téléphone sont repris de la fiche. Une fiche ne peut avoir qu'un seul compte.
  - **Personnel** : nom et prénom obligatoires. L'identifiant `prenom.nom` (sans accents) est proposé automatiquement, avec un suffixe 2, 3… s'il est déjà pris.
- **Mot de passe provisoire plutôt que choisi par la RH** : il est généré au hasard (12 caractères, sans 0/O ni 1/l pour éviter les confusions à la lecture) et affiché **une seule fois**. La personne doit le remplacer à sa première connexion : tant qu'elle ne l'a pas fait, toutes les pages la renvoient vers la page du mot de passe. Ainsi, la RH ne connaît jamais le mot de passe définitif. Le mot de passe provisoire passe par la session, stockée côté serveur, et non par les messages, qui peuvent être stockés dans un cookie.
- **Garde-fous** : la RH ne peut pas créer de compte **Direction Générale** (la DG, elle, peut). Personne ne peut, depuis l'espace RH, modifier **son propre compte**, un compte **DG** (sauf la DG) ni un compte **administrateur**. Cela évite qu'un compte RH s'attribue plus de droits ou bloque la direction.
- **Désactiver plutôt que supprimer** : la connexion est bloquée, mais les recettes, pointages et autres données restent dans l'historique. Générer un nouveau mot de passe déconnecte aussi les sessions déjà ouvertes de la personne.
- **Administration plus lisible** :
  - La section du profil s'appelle « Rôle et rattachement » et apparaît directement dans le formulaire, au lieu du lien « Ajouter un objet Profile supplémentaire ».
  - Chaque champ a un libellé en français et, quand c'est utile, une aide (« Détermine l'espace auquel la personne a accès », « Sert au calcul de l'âge du parc »…).
  - Le champ « Prénom » de Django, où l'application range le nom complet, s'appelle « Nom affiché ».
  - Migration `0004`.
- **Pas de lien « mot de passe oublié » par e-mail** : il faudrait configurer un serveur d'envoi d'e-mails, et les chauffeurs n'ont pas tous une adresse. La procédure retenue passe par la RH, qui génère un nouveau mot de passe.

## 10. Déploiement — GitHub Actions, Docker, Render, PostgreSQL (26/11/2026)

- **Base de données** : lue dans `DATABASE_URL` (bibliothèque `dj-database-url`). Sans cette variable, l'application reste sur SQLite en local. Sur Render, les identifiants PostgreSQL sont **générés par Render** et injectés automatiquement (`render.yaml`, `fromDatabase`) : personne n'a à les saisir.
- **Compte administrateur par variables** : l'offre gratuite de Render n'offre pas de terminal, donc pas de `createsuperuser`. La commande `creer_admin`, lancée à chaque démarrage, crée le compte à partir de `DJANGO_SUPERUSER_*` **s'il n'existe pas**, puis ne le modifie plus jamais. Un mot de passe faible arrête le démarrage avec un message clair. Le compte reçoit aussi le rôle DG pour voir tous les espaces.
- **Migrations au démarrage du conteneur** (et non à la construction) : la base de Render n'est pas joignable pendant la construction de l'image Docker. Cela convient tant qu'il n'y a qu'une instance.
- **Fichiers statiques par WhiteNoise**, sans serveur web séparé ; ils sont collectés à la construction de l'image.
- **Fichiers envoyés protégés** : `/media/…` n'est plus servi qu'aux utilisateurs connectés, par une vue Django. Avant, il n'était servi qu'en développement et sans contrôle. Les chemins qui sortent du dossier sont refusés. C'est suffisant pour le volume prévu ; au-delà, un stockage objet avec liens temporaires prendra le relais.
- **Sécurité du conteneur** : Gunicorn ne tourne pas en root. Le conteneur démarre en root uniquement pour donner le dossier media (un disque monté appartient souvent à root) à l'utilisateur `app`, puis se relance sous cet utilisateur.
- **Adresse Render automatique** (`RENDER_EXTERNAL_HOSTNAME`), ajoutée à `ALLOWED_HOSTS` et aux origines CSRF. Le **contrôle de santé** `/sante/` vérifie aussi la base, et il est exempté de la redirection HTTPS. Les requêtes vers un hôte inconnu sont refusées sans remplir les journaux.
- **CI** : tests sur un vrai PostgreSQL 16, vérification des migrations manquantes et `check --deploy`, puis construction de l'image, démarrage, et vérification qu'elle répond, sert le CSS et ne tourne pas en root.
- **Région Frankfurt** : la région Render la plus proche de Kinshasa parmi celles proposées.
- **Limites de l'offre gratuite, laissées en l'état** :
  - La base gratuite expire après 30 jours.
  - Le service s'endort après 15 minutes sans visite.
  - Sans disque, les photos sont perdues au redémarrage.
  - Le disque persistant est prévu dans `render.yaml`, en commentaire, pour l'offre payante.
- **Vérifié ici** : les 104 tests passent sur SQLite et sur PostgreSQL 16 ; le démarrage de production a été simulé sur PostgreSQL avec Gunicorn (migrations, compte admin, redirection HTTPS, cookies sécurisés, CSS, médias protégés, connexion). **Non vérifié ici** : la construction de l'image Docker (Docker Hub n'est pas accessible depuis mon environnement). C'est la CI qui la construit et la teste à chaque push.
