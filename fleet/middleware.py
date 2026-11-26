# -*- coding: utf-8 -*-
"""Oblige un employé à changer son mot de passe provisoire avant d'utiliser l'application."""
from django.conf import settings
from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse


class ChangementMotDePasseObligatoire:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = request.user
        if user.is_authenticated and getattr(getattr(user, "profile", None), "doit_changer_mdp", False):
            libres = (reverse("fleet:mot_de_passe"), reverse("logout"),
                      settings.STATIC_URL, settings.MEDIA_URL)
            if not any(request.path.startswith(p if p.startswith("/") else "/" + p) for p in libres):
                messages.info(request, "Bienvenue ! Choisissez votre mot de passe personnel pour continuer.")
                return redirect("fleet:mot_de_passe")
        return self.get_response(request)
