"""Configuration du projet Fleet Manager (prototype Django).

Les réglages sensibles se lisent dans les variables d'environnement
(voir `.env.example`). Sans variable, le projet démarre en mode développement.
"""
import os
from pathlib import Path

import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name, default):
    return os.environ.get(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


def env_list(name, default):
    raw = os.environ.get(name)
    return [x.strip() for x in raw.split(",") if x.strip()] if raw else default


# Mode développement par défaut (prototype) ; DJANGO_DEBUG=0 en production.
DEBUG = env_bool("DJANGO_DEBUG", True)

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY")
if not SECRET_KEY:
    if not DEBUG:
        raise RuntimeError("DJANGO_SECRET_KEY doit être défini quand DJANGO_DEBUG=0.")
    SECRET_KEY = "django-insecure-dev-only-ne-pas-utiliser-en-production"

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS",
                         ["localhost", "127.0.0.1", "[::1]"] if DEBUG else [])
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS", [])

# Render fournit automatiquement l'adresse publique du service (xxx.onrender.com).
RENDER_EXTERNAL_HOSTNAME = os.environ.get("RENDER_EXTERNAL_HOSTNAME")
if RENDER_EXTERNAL_HOSTNAME:
    ALLOWED_HOSTS.append(RENDER_EXTERNAL_HOSTNAME)
    CSRF_TRUSTED_ORIGINS.append(f"https://{RENDER_EXTERNAL_HOSTNAME}")

# Affiche les comptes de démo sur la page de connexion (désactivé hors DEBUG).
SHOW_DEMO_ACCOUNTS = env_bool("FLEET_SHOW_DEMO_ACCOUNTS", DEBUG)

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "fleet",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # Sert les fichiers statiques (CSS de l'administration) en production.
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "fleet.middleware.ChangementMotDePasseObligatoire",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "fleet_manager.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "fleet.context_processors.fleet_settings",
            ],
        },
    },
]

WSGI_APPLICATION = "fleet_manager.wsgi.application"

# DATABASE_URL (ex. postgresql://user:motdepasse@hote:5432/base) ; sans elle : SQLite local.
# Sur Render, DATABASE_URL est remplie automatiquement par la base PostgreSQL (render.yaml).
DATABASES = {
    "default": dj_database_url.config(
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
        conn_max_age=600, conn_health_checks=True),
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "fr-fr"
TIME_ZONE = "Africa/Kinshasa"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "media/"
# Dossier des fichiers envoyés (captures, photos). Sur Render : le chemin d'un disque persistant.
MEDIA_ROOT = Path(os.environ.get("FLEET_MEDIA_ROOT", BASE_DIR / "media"))

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    # En production : fichiers compressés et nommés avec une empreinte (cache navigateur sûr).
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage" if DEBUG
                    else "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Uploads (captures de versement, photos de panne)
FLEET_UPLOAD_MAX_BYTES = 5 * 1024 * 1024
# Monnaie : franc congolais (code ISO CDF, symbole affiché « FC »). Montants entiers.
FLEET_DEVISE = os.environ.get("FLEET_DEVISE", "FC")
FLEET_MONTANT_FIXE_DEFAUT = int(os.environ.get("FLEET_MONTANT_FIXE_DEFAUT", 100000))
FLEET_MAP_CENTER = (-4.322, 15.312)   # Kinshasa (Gombe)
FLEET_MAP_ZOOM = 12
# Pointage : arrivée après cette heure = retard.
FLEET_HEURE_RETARD = os.environ.get("FLEET_HEURE_RETARD", "07:30")
# Hypothèses de pilotage, à ajuster selon la convention et la politique de l'entreprise.
# RDC : loi n° 16/009 du 15/07/2016 (régime général de sécurité sociale) -> 65 ans.
FLEET_AGE_RETRAITE = int(os.environ.get("FLEET_AGE_RETRAITE", 65))                       # ans
FLEET_AGE_RENOUVELLEMENT_VEHICULE = int(os.environ.get("FLEET_AGE_RENOUVELLEMENT_VEHICULE", 8))  # ans

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "fleet:home"
LOGOUT_REDIRECT_URL = "login"

# ------------------------------------------------------------------ LOGGING
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "simple": {"format": "{asctime} {levelname} {name} : {message}", "style": "{"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "simple"},
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "django": {"handlers": ["console"], "level": os.environ.get("DJANGO_LOG_LEVEL", "INFO"),
                   "propagate": False},
        # Les 403/404 sont normaux (accès refusé, id inconnu) : on ne journalise
        # pas leur traceback ; les erreurs 500 restent journalisées.
        "django.request": {"handlers": ["console"], "level": "ERROR", "propagate": False},
        # Requêtes avec un nom d'hôte inconnu (robots, scanners) : refusées en 400, sans trace.
        "django.security.DisallowedHost": {"handlers": [], "level": "CRITICAL", "propagate": False},
    },
}

# ------------------------------------------------------------------ PRODUCTION
if not DEBUG:
    SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_SSL_REDIRECT", True)
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    # Cookies envoyés uniquement en HTTPS (désactivable pour un essai local en HTTP).
    SESSION_COOKIE_SECURE = CSRF_COOKIE_SECURE = env_bool("DJANGO_COOKIES_SECURISES", True)
    SECURE_HSTS_SECONDS = int(os.environ.get("DJANGO_HSTS_SECONDS", 0))
    SECURE_CONTENT_TYPE_NOSNIFF = True
    # Le contrôle de santé de Render peut arriver en HTTP interne.
    SECURE_REDIRECT_EXEMPT = [r"^sante/$"]
