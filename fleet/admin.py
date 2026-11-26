# -*- coding: utf-8 -*-
"""Back-office Django : gestion de toutes les tables (équivalent AppSheet)."""
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User
from django.utils import timezone

from .models import (Attribution, Chauffeur, Conge, Depense, Panne, Presence,
                     Profile, Recette, Vehicule)

admin.site.site_header = "Fleet Manager — Administration"
admin.site.site_title = "Fleet Manager"
admin.site.index_title = "Gestion de flotte"


class ProfileInline(admin.StackedInline):
    """Le rôle s'affiche directement dans la fiche du compte (plus de lien « Ajouter un objet Profile »)."""
    model = Profile
    can_delete = False
    extra = 1
    max_num = 1
    fields = ("role", "chauffeur", "service", "tel", "doit_changer_mdp")
    autocomplete_fields = ("chauffeur",)


class UserAdmin(BaseUserAdmin):
    inlines = [ProfileInline]
    list_display = ("username", "first_name", "email", "role", "is_active", "is_staff")
    list_filter = BaseUserAdmin.list_filter + ("profile__role",)
    list_select_related = ("profile",)

    @admin.display(description="Rôle", ordering="profile__role")
    def role(self, obj):
        return obj.profile.get_role_display() if obj.role_name else "—"

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        champ = super().formfield_for_dbfield(db_field, request, **kwargs)
        # L'application range le nom complet dans first_name (« Nom Prénom »).
        if db_field.name == "first_name" and champ:
            champ.label = "Nom affiché"
            champ.help_text = "Nom et prénom, tels qu'ils apparaissent dans l'application (ex. « Kanku Albert »)."
        if db_field.name == "last_name" and champ:
            champ.help_text = "Facultatif : laissez vide, le nom affiché suffit."
        return champ


admin.site.unregister(User)
admin.site.register(User, UserAdmin)


@admin.register(Chauffeur)
class ChauffeurAdmin(admin.ModelAdmin):
    list_display = ("nom", "prenom", "tel", "permis", "statut", "date_expiration_permis")
    list_filter = ("statut", "permis")
    search_fields = ("nom", "prenom", "tel", "email")


@admin.register(Vehicule)
class VehiculeAdmin(admin.ModelAdmin):
    list_display = ("plaque", "marque", "modele", "situation", "kilometrage",
                    "prochain_ct", "assurance_expire")
    list_filter = ("situation", "marque", "type_vehicule", "carburant")
    search_fields = ("plaque", "marque", "modele", "numero_chassis")


@admin.register(Recette)
class RecetteAdmin(admin.ModelAdmin):
    list_display = ("date", "saisie_le", "num_ordre", "chauffeur", "vehicule", "percepteur",
                    "montant_verse", "montant_fixe", "cloturee")
    list_filter = ("cloturee", "date")
    search_fields = ("chauffeur__nom", "chauffeur__prenom", "vehicule__plaque")
    autocomplete_fields = ("chauffeur", "vehicule", "percepteur")
    readonly_fields = ("saisi_par",)
    date_hierarchy = "date"
    list_select_related = ("chauffeur", "vehicule", "percepteur")

    def save_model(self, request, obj, form, change):
        if not obj.saisi_par:
            obj.saisi_par = request.user.get_full_name() or request.user.username
        super().save_model(request, obj, form, change)


@admin.register(Panne)
class PanneAdmin(admin.ModelAdmin):
    list_display = ("id", "date_declaration", "vehicule", "priorite", "statut", "declaree_par")
    list_filter = ("statut", "priorite")
    search_fields = ("description", "vehicule__plaque")
    autocomplete_fields = ("vehicule", "declaree_par")
    date_hierarchy = "date_declaration"
    list_select_related = ("vehicule", "declaree_par")


@admin.register(Depense)
class DepenseAdmin(admin.ModelAdmin):
    list_display = ("date", "type_dep", "categorie", "montant", "vehicule", "saisi_par")
    list_filter = ("type_dep", "categorie")
    search_fields = ("categorie", "vehicule__plaque", "justificatif", "commentaire")
    autocomplete_fields = ("vehicule",)
    readonly_fields = ("saisi_par",)
    date_hierarchy = "date"
    list_select_related = ("vehicule",)

    def save_model(self, request, obj, form, change):
        if not obj.saisi_par:
            obj.saisi_par = request.user.get_full_name() or request.user.username
        super().save_model(request, obj, form, change)


@admin.register(Attribution)
class AttributionAdmin(admin.ModelAdmin):
    list_display = ("chauffeur", "vehicule", "date_debut", "date_fin", "actif", "gelee")
    list_filter = ("actif", "gelee")
    search_fields = ("chauffeur__nom", "chauffeur__prenom", "vehicule__plaque")
    autocomplete_fields = ("chauffeur", "vehicule", "nouveau_chauffeur", "attribue_par")
    date_hierarchy = "date_debut"
    list_select_related = ("chauffeur", "vehicule")

    def save_model(self, request, obj, form, change):
        # Cohérence : une attribution désactivée doit avoir une date de fin,
        # une attribution active n'en a pas.
        if not obj.actif and not obj.date_fin:
            obj.date_fin = timezone.localdate()
        if obj.actif:
            obj.date_fin = None
        if not obj.attribue_par_id:
            obj.attribue_par = request.user
        super().save_model(request, obj, form, change)


@admin.register(Presence)
class PresenceAdmin(admin.ModelAdmin):
    list_display = ("date", "nom", "heure_arrivee", "heure_depart", "statut", "pointe_par")
    list_filter = ("statut",)
    search_fields = ("nom", "chauffeur__nom", "chauffeur__prenom")
    autocomplete_fields = ("chauffeur", "pointe_par", "user")
    list_select_related = ("pointe_par",)
    date_hierarchy = "date"


@admin.register(Conge)
class CongeAdmin(admin.ModelAdmin):
    list_display = ("chauffeur", "type_conge", "date_debut", "date_fin", "statut")
    list_filter = ("statut", "type_conge")
    search_fields = ("chauffeur__nom", "chauffeur__prenom")
    autocomplete_fields = ("chauffeur",)
    date_hierarchy = "date_debut"
    list_select_related = ("chauffeur",)
