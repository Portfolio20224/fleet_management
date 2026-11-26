# -*- coding: utf-8 -*-
"""Contrôle d'accès par rôle, vérifié côté serveur."""
from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied


def _check(request, roles):
    """Renvoie une réponse de redirection, lève PermissionDenied, ou None si OK."""
    if not request.user.is_authenticated:
        # Conserve la page demandée (?next=...) pour y revenir après connexion.
        return redirect_to_login(request.get_full_path())
    if request.user.role_name not in roles:
        raise PermissionDenied("Accès réservé au(x) rôle(s) : " + " / ".join(roles))
    return None


def role_required(*roles):
    """Décorateur de vue-fonction : bloque si l'utilisateur n'a aucun des rôles."""
    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            refus = _check(request, roles)
            return refus or view(request, *args, **kwargs)
        wrapper.roles = roles
        return wrapper
    return decorator


class RoleRequiredMixin:
    """Équivalent pour les vues-classes : `class MaVue(RoleRequiredMixin, View): roles = ("DG",)`."""
    roles = ()

    def dispatch(self, request, *args, **kwargs):
        refus = _check(request, self.roles)
        return refus or super().dispatch(request, *args, **kwargs)
