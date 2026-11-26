# -*- coding: utf-8 -*-
"""Crée le compte administrateur à partir de variables d'environnement, s'il n'existe pas.

Lancée à chaque démarrage du conteneur (voir docker/entrypoint.sh) : utile sur Render,
dont l'offre gratuite ne donne pas accès à un terminal pour faire `createsuperuser`.

    DJANGO_SUPERUSER_USERNAME   identifiant (sans elle, la commande ne fait rien)
    DJANGO_SUPERUSER_PASSWORD   mot de passe (doit respecter les règles de sécurité)
    DJANGO_SUPERUSER_EMAIL      facultatif

Le compte n'est jamais modifié s'il existe déjà : changer la variable ne change pas le
mot de passe (on le change dans l'application, bouton « Mot de passe »). Une fois le
compte créé, on peut supprimer DJANGO_SUPERUSER_PASSWORD des variables de Render.
"""
import os

from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from fleet.models import Profile


class Command(BaseCommand):
    help = "Crée le superutilisateur depuis DJANGO_SUPERUSER_* s'il n'existe pas encore."

    def handle(self, *args, **options):
        ident = os.environ.get("DJANGO_SUPERUSER_USERNAME", "").strip()
        if not ident:
            self.stdout.write("creer_admin : DJANGO_SUPERUSER_USERNAME absent, rien à faire.")
            return
        if User.objects.filter(username__iexact=ident).exists():
            self.stdout.write(f"creer_admin : le compte « {ident} » existe déjà, inchangé.")
            return

        mdp = os.environ.get("DJANGO_SUPERUSER_PASSWORD", "")
        if not mdp:
            raise CommandError("DJANGO_SUPERUSER_PASSWORD est vide : impossible de créer l'administrateur.")
        email = os.environ.get("DJANGO_SUPERUSER_EMAIL", "").strip()
        try:
            validate_password(mdp, User(username=ident, email=email))
        except ValidationError as e:
            raise CommandError("Mot de passe administrateur refusé : " + " ".join(e.messages))

        u = User.objects.create_superuser(username=ident, email=email, password=mdp,
                                          first_name="Administrateur")
        # Rôle DG : l'administrateur voit aussi tous les espaces de l'application.
        Profile.objects.create(user=u, role=Profile.Roles.DG, service="Administration")
        self.stdout.write(self.style.SUCCESS(f"creer_admin : administrateur « {ident} » créé."))
