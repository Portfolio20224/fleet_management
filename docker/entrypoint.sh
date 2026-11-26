#!/bin/sh
# Démarrage du conteneur : migrations, compte administrateur, puis la commande (Gunicorn).
set -e

# 1) Lancé en root : on prépare le dossier des fichiers envoyés, puis on se relance en « app ».
if [ "$(id -u)" = "0" ]; then
    MEDIA_DIR="${FLEET_MEDIA_ROOT:-/app/media}"
    mkdir -p "$MEDIA_DIR"
    chown -R app:app "$MEDIA_DIR"
    exec setpriv --reuid=app --regid=app --init-groups "$0" "$@"
fi

# 2) À partir d'ici : utilisateur « app » (sans privilèges).

echo "==> Migrations de la base de données"
python manage.py migrate --noinput

echo "==> Compte administrateur (si DJANGO_SUPERUSER_USERNAME est défini)"
python manage.py creer_admin

if [ "${FLEET_SEED_DEMO:-0}" = "1" ]; then
    echo "==> Données de démonstration (FLEET_SEED_DEMO=1 : EFFACE et recrée les données à chaque démarrage !)"
    python manage.py seed_demo
fi

exec "$@"
