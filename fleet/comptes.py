# -*- coding: utf-8 -*-
"""Gestion des comptes depuis l'espace RH : règles de droits et mots de passe provisoires."""
import secrets

from django.contrib.auth.models import User

from .models import Profile
from .utils import slug_ascii

# Caractères sans ambiguïté à la lecture (pas de 0/O, 1/l/I) : le mot de passe est dicté ou recopié.
_ALPHABET = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def mot_de_passe_provisoire():
    """Ex. « k7Pq-x3Zm-T9wd » : 12 caractères aléatoires, à changer à la 1re connexion."""
    return "-".join("".join(secrets.choice(_ALPHABET) for _ in range(4)) for _ in range(3))


def identifiant_libre(prenom, nom):
    """« Jean-Marie », « Tshibangu » -> « jean-marie.tshibangu » (suffixe 2, 3… si déjà pris)."""
    base = f"{slug_ascii(prenom)}.{slug_ascii(nom)}"[:140]
    ident, n = base, 1
    while User.objects.filter(username__iexact=ident).exists():
        n += 1
        ident = f"{base}{n}"
    return ident


def roles_attribuables(acteur):
    """La RH crée tous les comptes sauf Direction Générale ; la DG peut tout créer."""
    roles = Profile.Roles.choices
    if acteur.role_name != "DG":
        roles = [r for r in roles if r[0] != Profile.Roles.DG]
    return roles


def peut_gerer(acteur, cible):
    """L'acteur (RH ou DG) peut-il réinitialiser / désactiver ce compte ?

    Jamais : soi-même, un administrateur (superuser ou accès admin), et pour la RH un compte DG.
    Ces comptes-là se gèrent dans l'administration.
    """
    if cible.pk == acteur.pk or cible.is_superuser or cible.is_staff:
        return False
    if cible.role_name == Profile.Roles.DG and acteur.role_name != "DG":
        return False
    return True
