# Déploiement — GitHub Actions, Docker, Render, PostgreSQL

## Vue d'ensemble

```
git push ──► GitHub ──► GitHub Actions : tests sur PostgreSQL + construction de l'image Docker
                   └──► Render : construit l'image (Dockerfile) et la démarre
                                 ├─ au démarrage : migrations + compte administrateur
                                 └─ base PostgreSQL gérée par Render (DATABASE_URL automatique)
```

| Fichier | Rôle |
|---|---|
| `.github/workflows/ci.yml` | Tests à chaque `push` (PostgreSQL 16), puis construction et essai de l'image Docker |
| `Dockerfile` | Image de production : Python 3.13, Gunicorn, fichiers statiques via WhiteNoise |
| `docker/entrypoint.sh` | Au démarrage : migrations, compte administrateur, puis Gunicorn (sans droits root) |
| `docker-compose.yml` | Essai de l'image sur votre ordinateur, avec PostgreSQL |
| `render.yaml` | « Blueprint » Render : crée la base et le service web, et les relie |

## Ce que vous devez définir, et ce qui est automatique

| Élément | Qui s'en occupe |
|---|---|
| Identifiants PostgreSQL (utilisateur, mot de passe, hôte) | **Render, automatiquement.** Ils sont générés à la création de la base et transmis à l'application dans `DATABASE_URL`. Vous n'avez rien à saisir. |
| `DJANGO_SECRET_KEY` | **Render, automatiquement** (tirée au hasard une fois, puis conservée). |
| Adresse `xxx.onrender.com` (ALLOWED_HOSTS, CSRF) | **Automatique** (variable `RENDER_EXTERNAL_HOSTNAME`). |
| Migrations de la base | **Automatique**, à chaque démarrage. |
| **Compte administrateur** | **Vous**, une fois : `DJANGO_SUPERUSER_USERNAME`, `DJANGO_SUPERUSER_PASSWORD`, `DJANGO_SUPERUSER_EMAIL`. Render les demande à la création du Blueprint. Le compte est créé au premier démarrage. |
| Nom de domaine personnel (facultatif) | **Vous** : `DJANGO_ALLOWED_HOSTS` (ex. `fleet.mondomaine.cd`), plus le domaine dans Render. |

Pourquoi des variables pour l'administrateur plutôt que `createsuperuser` ? L'offre gratuite de Render
ne donne **pas accès à un terminal** sur le serveur. La commande `creer_admin` lit ces variables au
démarrage et crée le compte **s'il n'existe pas** ; elle ne le modifie jamais ensuite. Le mot de passe
doit respecter les règles de sécurité (8 caractères minimum, pas uniquement des chiffres, pas trop
courant), sinon le démarrage s'arrête avec un message clair dans les journaux Render.

Une fois connecté, changez ce mot de passe (bouton « Mot de passe ») et **supprimez
`DJANGO_SUPERUSER_PASSWORD`** des variables Render : il n'est plus utile.

## Étapes

1. **Mettre le projet sur GitHub**, puis pousser (`git push`). Ouvrez l'onglet *Actions* du dépôt :
   les deux étapes « Tests (PostgreSQL) » et « Image Docker » doivent passer au vert.
2. **Render** : *New* → *Blueprint* → choisir le dépôt. Render lit `render.yaml` et propose de créer
   `fleet-db` (PostgreSQL) et `fleet-manager` (service web).
3. **Renseigner les variables demandées** : identifiant, mot de passe et e-mail de l'administrateur ;
   `DJANGO_ALLOWED_HOSTS` peut rester vide si vous utilisez l'adresse `onrender.com`.
4. **Lancer.** Le premier déploiement prend quelques minutes. Dans les journaux du service, vous devez
   voir : `Migrations de la base de données`, puis `administrateur « … » créé`.
5. **Ouvrir** l'adresse `https://fleet-manager-xxxx.onrender.com`, se connecter avec le compte
   administrateur, puis créer les comptes des employés (espace RH → onglet « Comptes »).

Ensuite, chaque `git push` sur la branche principale redéploie automatiquement l'application.

## Offre gratuite : à savoir avant d'y mettre de vraies données

- **La base PostgreSQL gratuite expire 30 jours après sa création** (puis 14 jours de grâce avant
  suppression). Pour de vraies données, passez la base à une offre payante, dans Render ou dans
  `render.yaml` (`plan:`).
- **Le service gratuit s'endort après 15 minutes sans visite** ; la première visite suivante prend
  environ une minute.
- **Pas de disque persistant** : les photos et captures envoyées sont **perdues** au redémarrage.
  Pour les garder : offre payante + disque (lignes `disk:` à décommenter dans `render.yaml`, et
  `FLEET_MEDIA_ROOT=/var/data/media`), ou plus tard un stockage objet (S3, Cloudflare R2…).

Les fichiers envoyés ne sont visibles que par les utilisateurs connectés (`/media/…` exige une connexion).

## Essayer l'image sur votre ordinateur

```bash
docker compose up --build
```

Puis http://localhost:8000 avec `admin` / `Admin-Local-2026`, ou les comptes de démonstration
(`FLEET_SEED_DEMO=1` dans `docker-compose.yml` recharge les données de démo à chaque démarrage).

## Après la mise en ligne

- Quand le HTTPS fonctionne bien, activez HSTS : `DJANGO_HSTS_SECONDS=3600`, puis `31536000`.
- Les erreurs apparaissent dans l'onglet *Logs* du service Render.
- Ne mettez **jamais** `FLEET_SEED_DEMO=1` sur Render : cela effacerait les données à chaque démarrage.
