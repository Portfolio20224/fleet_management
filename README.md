# Fleet Manager — Prototype Django

Application de gestion de flotte (compagnie de transport) : recettes journalières,
pannes, dépenses, RH, finance et direction. Architecture reprise d'un projet AppSheet,
reconstruite en Django (vraie base de données, authentification, contrôle d'accès par rôle).

## Différences avec le prototype Streamlit

| | Streamlit | Django (ce projet) |
|---|---|---|
| Base de données | Fichiers CSV / session | **SQLite persistante** (PostgreSQL en prod) |
| Sécurité | Vérification côté client | **Contrôle d'accès côté serveur** |
| Back-office | Aucun | **/admin/ gratuit** (équivalent Google Sheets/AppSheet) |
| Photos / caméra | capture d'écran session | **Uploads réels** (media/), images vérifiées, 5 Mo max. |
| Mise en production | Limitée (dashboards internes) | **Classique** (WSGI/ASGI : Render, Railway…) |

## Installation et lancement

```bash
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_demo        # charge les données de démonstration
python manage.py runserver
```

Puis ouvrez http://127.0.0.1:8000

> **Mise à jour depuis la version précédente** : la migration initiale est désormais
> fournie (`fleet/migrations/0001_initial.py`). Si vous aviez généré vos propres
> migrations, supprimez `db.sqlite3` et vos anciens fichiers `fleet/migrations/0*.py`,
> puis relancez `migrate` et `seed_demo` (les données de démo sont régénérées).

## Comptes de démonstration

| Utilisateur | Mot de passe | Rôle |
|---|---|---|
| `dg` | demo1234 | Direction Générale (accès à tout) |
| `finance` | demo1234 | Trésorier / Finance |
| `rh` | demo1234 | Ressources Humaines |
| `tech` | demo1234 | Service Technique |
| `per1`, `per2`, `per3` | demo1234 | Percepteurs |
| `chauf1`, `chauf2`, `chauf3` | demo1234 | Chauffeurs |

Ces comptes sont rappelés sur la page de connexion **uniquement en mode DEBUG**
(ou si `FLEET_SHOW_DEMO_ACCOUNTS=1`).

Back-office : http://127.0.0.1:8000/admin/ (créer un superutilisateur avec
`python manage.py createsuperuser`). Le lien n'apparaît sur l'accueil que pour les comptes `is_staff`.

## Comptes utilisateurs

1. **Administrateur** (une seule fois, à l'installation) : `python manage.py createsuperuser`.
2. **Comptes des employés** : la RH (ou la DG) les crée dans l'espace RH, onglet **« Comptes »**.
   Pour un chauffeur, on choisit sa fiche (créée avant dans l'onglet « Chauffeurs ») ; pour le personnel,
   on saisit nom et prénom. L'identifiant est proposé automatiquement (`prenom.nom`).
3. Un **mot de passe provisoire** s'affiche une seule fois : la RH le remet à l'employé, qui doit en
   choisir un nouveau à sa première connexion.
4. Chacun peut ensuite changer son mot de passe avec le bouton **« Mot de passe »** de la barre du haut.
   En cas d'oubli, la RH clique sur « Nouveau mot de passe ».
5. Pour un départ, la RH **désactive** le compte (l'historique est conservé).

La RH ne peut ni créer ni modifier un compte Direction Générale ou administrateur, ni son propre compte
depuis cet onglet : ces cas passent par la DG ou par `/admin/`.

## Les 6 espaces

| URL | Espace | Contenu |
|---|---|---|
| `/percepteur/` | Percepteur | Saisie recette par double clic (véhicule attribué pré-sélectionné, 1 recette par chauffeur sur 12 h), caméra mobile, missions du jour, clôture multiple |
| `/chauffeur/` | Chauffeur | Pointage du jour (lecture seule), véhicule attribué, panne + photo, historique, statistiques personnelles |
| `/technique/` | Technique | Kanban 4 colonnes (Déclarée → Terminée) |
| `/rh/` | RH | Chauffeurs, **pointage du jour**, attributions avec gel, congés, état véhicules, statistiques par chauffeur, pyramide des âges |
| `/finance/` | Trésorier | KPI J/S/M, **ajout de dépense**, graphiques Chart.js, trésorerie, exports CSV |
| `/dg/` | DG | KPI, carte Leaflet/OSM, alertes critiques, **âge du parc et ajout de véhicule**, rapports mensuels CSV |

Un accès à un espace non autorisé renvoie une page **403** ; un visiteur non connecté
est redirigé vers la connexion puis ramené à la page demandée.

## Tests

```bash
python manage.py test fleet
```

104 tests (environ 1 minute), qui couvrent environ 99 % du code de l'application : contrôle d'accès
par rôle, règles métier (recette unique sur 12 h, pointage, congés, étapes des pannes), formulaires
et leurs refus, alertes DG, statistiques, comptes et mots de passe, exports CSV, pages
d'administration et cohérence des données de démonstration. Les fichiers envoyés pendant les tests
vont dans un dossier temporaire supprimé à la fin.

Pour mesurer la couverture :

```bash
pip install coverage
coverage run --source=fleet --omit="fleet/migrations/*,fleet/tests.py" manage.py test fleet
coverage report -m
```

## Configuration et production

Les réglages se lisent dans les variables d'environnement : voir `.env.example`.
Sans variable, le projet démarre en mode développement avec SQLite.

**Mise en ligne : voir [DEPLOIEMENT.md](DEPLOIEMENT.md)** (GitHub Actions, Docker, Render, PostgreSQL).
En résumé : `git push` lance les tests ; Render construit l'image, crée la base PostgreSQL, applique
les migrations et crée le compte administrateur au démarrage.

Essai local de l'image de production : `docker compose up --build`, puis http://localhost:8000.

## Notes

- Graphes (Chart.js) et carte (Leaflet/OpenStreetMap) chargés par CDN : connexion internet requise à l'affichage.
- Les photos et captures envoyées (`/media/…`) ne sont accessibles qu'aux utilisateurs connectés.
- Exports CSV compatibles Excel en français (séparateur `;`, UTF-8 avec BOM) ; les cellules
  commençant par `=`, `+`, `-`, `@` sont neutralisées contre l'injection de formules.
- Montants en **francs congolais (FC, code CDF)**, entiers (les centimes ne sont pas utilisés).
  Le symbole affiché se règle avec `FLEET_DEVISE`. Pour convertir une base existante saisie en FCFA :
  `python manage.py convertir_monnaie --taux 4.05` (aperçu), puis la même commande avec `--appliquer`.
  Relevez le taux du jour (environ 4 FC pour 1 FCFA fin 2026).
- Le pointage des chauffeurs est saisi par la RH (le chauffeur le consulte). Paramètres de pilotage
  dans `.env.example` : heure de retard, âge de départ à la retraite, âge de renouvellement d'un véhicule.
- Valeurs de statut : la base stocke des codes sans accents (`En conge`, `Termine`, `Gelee`…),
  l'interface affiche les libellés accentués (`En congé`, `Terminée`, `Gelée`…).
