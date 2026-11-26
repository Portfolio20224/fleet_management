# Image de production de Fleet Manager (Django + Gunicorn).
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8000

WORKDIR /app

# Dépendances d'abord : cette couche reste en cache tant que requirements.txt ne change pas.
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Fichiers statiques collectés à la construction (servis par WhiteNoise).
# DEBUG=0 pour produire le manifeste ; la clé n'est utilisée que pour cette étape.
RUN DJANGO_DEBUG=0 DJANGO_SECRET_KEY=construction-uniquement \
    python manage.py collectstatic --noinput

# Utilisateur sans privilèges. Le conteneur démarre en root uniquement pour donner le
# dossier media (disque monté, souvent propriété de root) à « app », puis l'entrypoint
# relance tout sous « app » : migrations et Gunicorn ne tournent jamais en root.
RUN useradd --create-home --uid 1000 app \
    && mkdir -p /app/media \
    && chown -R app:app /app/media \
    && chmod +x docker/entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["docker/entrypoint.sh"]
CMD ["sh", "-c", "gunicorn fleet_manager.wsgi:application --bind 0.0.0.0:${PORT} --workers ${WEB_CONCURRENCY:-2} --timeout 60 --access-logfile - --error-logfile -"]
