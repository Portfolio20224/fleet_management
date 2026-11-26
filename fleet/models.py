# -*- coding: utf-8 -*-
"""Modèles de données — équivalent des feuilles AppSheet, en base SQL.

Convention sur les `choices` : la valeur stockée en base reste un code ASCII
stable (ex. "En conge", "Termine") ; seul le libellé affiché porte les accents
(ex. "En congé", "Terminé"). Dans les gabarits, utiliser `get_<champ>_display`.
"""
from datetime import timedelta

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class Profile(models.Model):
    """Extension du user Django : rôle, service, téléphone, lien chauffeur."""
    class Roles(models.TextChoices):
        DG = "DG", "Direction Générale"
        TRESORIER = "TRESORIER", "Trésorier / Finance"
        RH = "RH", "Ressources Humaines"
        TECHNIQUE = "TECHNIQUE", "Service Technique"
        PERCEPTEUR = "PERCEPTEUR", "Percepteur"
        CHAUFFEUR = "CHAUFFEUR", "Chauffeur"

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile",
                                verbose_name="compte")
    role = models.CharField("rôle", max_length=20, choices=Roles.choices,
                            help_text="Détermine l'espace auquel la personne a accès.")
    service = models.CharField(max_length=100, blank=True)
    tel = models.CharField("téléphone", max_length=30, blank=True)
    chauffeur = models.ForeignKey("Chauffeur", null=True, blank=True, on_delete=models.SET_NULL,
                                  verbose_name="fiche chauffeur liée",
                                  help_text="Uniquement pour le rôle Chauffeur : relie le compte à sa fiche.")
    doit_changer_mdp = models.BooleanField(
        "doit changer son mot de passe", default=False,
        help_text="Coché : la personne devra choisir un nouveau mot de passe à sa prochaine connexion.")

    class Meta:
        verbose_name = "rôle et rattachement"
        verbose_name_plural = "rôles et rattachements"

    def __str__(self):
        return f"{self.user.username} ({self.get_role_display()})"


class Chauffeur(models.Model):
    STATUTS = [("Actif", "Actif"), ("En conge", "En congé"), ("Suspendu", "Suspendu")]
    nom = models.CharField(max_length=50)
    prenom = models.CharField("prénom", max_length=50)
    email = models.EmailField(blank=True)
    tel = models.CharField("téléphone", max_length=30, blank=True)
    permis = models.CharField("catégorie de permis", max_length=5, default="B")
    date_naissance = models.DateField("date de naissance", null=True, blank=True)
    date_embauche = models.DateField("date d'embauche", null=True, blank=True)
    statut = models.CharField(max_length=20, choices=STATUTS, default="Actif")
    photo = models.ImageField(upload_to="chauffeurs/", blank=True)
    date_expiration_permis = models.DateField("expiration du permis", null=True, blank=True)
    adresse = models.CharField(max_length=255, blank=True)
    personne_contact = models.CharField("personne à contacter", max_length=100, blank=True)
    contact_urgence = models.CharField("téléphone d'urgence", max_length=30, blank=True)

    def __str__(self):
        return f"{self.nom} {self.prenom}"


class Vehicule(models.Model):
    SITUATIONS = [("En service", "En service"), ("En panne", "En panne"),
                  ("En maintenance", "En maintenance"), ("Gelee", "Gelée")]
    plaque = models.CharField(max_length=20, unique=True)
    marque = models.CharField(max_length=50)
    modele = models.CharField("modèle", max_length=50)
    numero_chassis = models.CharField("numéro de châssis", max_length=50, blank=True)
    carburant = models.CharField(max_length=20, default="Diesel")
    annee_fabrication = models.IntegerField("année de fabrication", null=True, blank=True)
    date_acquisition = models.DateField("date d'acquisition", null=True, blank=True,
                                        help_text="Sert au calcul de l'âge du parc.")
    type_vehicule = models.CharField("type de véhicule", max_length=30, blank=True)
    categorie = models.CharField("catégorie", max_length=50, blank=True)
    kilometrage = models.IntegerField("kilométrage", default=0)
    situation = models.CharField(max_length=20, choices=SITUATIONS, default="En service")
    prochain_ct = models.DateField("prochain contrôle technique", null=True, blank=True)
    assurance_expire = models.DateField("fin d'assurance", null=True, blank=True)
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)

    class Meta:
        verbose_name = "véhicule"

    def __str__(self):
        return f"{self.plaque} ({self.marque} {self.modele})"


class Recette(models.Model):
    # Montants en francs congolais (CDF) : les centimes ne sont pas utilisés, l'entier est volontaire.
    # Une recette par chauffeur sur une fenêtre glissante (voir DELAI_ENTRE_RECETTES).
    DELAI_ENTRE_RECETTES = timedelta(hours=12)

    date = models.DateField()
    saisie_le = models.DateTimeField("saisie le", default=timezone.now, db_index=True)
    num_ordre = models.IntegerField("n° d'ordre du jour", default=1)
    chauffeur = models.ForeignKey(Chauffeur, on_delete=models.PROTECT)
    vehicule = models.ForeignKey(Vehicule, on_delete=models.PROTECT, verbose_name="véhicule")
    percepteur = models.ForeignKey(User, on_delete=models.PROTECT)
    montant_verse = models.IntegerField("montant versé", default=0)
    montant_fixe = models.IntegerField("montant fixe attendu", default=0)
    observation = models.TextField(blank=True)
    capture = models.FileField("capture du versement", upload_to="captures/", blank=True)
    saisi_par = models.CharField("saisi par", max_length=100, blank=True)
    cloturee = models.BooleanField("clôturée", default=False)

    class Meta:
        ordering = ["-date", "-num_ordre"]
        constraints = [
            models.UniqueConstraint(fields=["date", "num_ordre"],
                                    name="recette_ordre_unique_par_jour"),
        ]

    def __str__(self):
        return f"Recette {self.id} du {self.date:%d/%m/%Y}"


class Panne(models.Model):
    ETAPES = [("Declare", "Déclarée"), ("En diagnostic", "En diagnostic"),
              ("En reparation", "En réparation"), ("Termine", "Terminée")]
    PRIORITES = [("Faible", "Faible"), ("Moyenne", "Moyenne"),
                 ("Haute", "Haute"), ("Critique", "Critique")]
    date_declaration = models.DateField("date de déclaration")
    vehicule = models.ForeignKey(Vehicule, on_delete=models.CASCADE, verbose_name="véhicule")
    declaree_par = models.ForeignKey(Chauffeur, null=True, blank=True,
                                     on_delete=models.SET_NULL, verbose_name="déclarée par")
    description = models.TextField()
    priorite = models.CharField("priorité", max_length=20, choices=PRIORITES, default="Moyenne")
    statut = models.CharField("étape", max_length=20, choices=ETAPES, default="Declare")
    photo = models.FileField(upload_to="pannes/", blank=True)

    def __str__(self):
        return f"Panne {self.id} — {self.vehicule.plaque}"


class Depense(models.Model):
    TYPES = [("Operationnelle", "Opérationnelle"), ("Fixe", "Fixe")]
    date = models.DateField()
    type_dep = models.CharField("type", max_length=20, choices=TYPES, default="Operationnelle")
    categorie = models.CharField("catégorie", max_length=50)
    montant = models.IntegerField(default=0)
    vehicule = models.ForeignKey(Vehicule, null=True, blank=True, on_delete=models.SET_NULL,
                                 verbose_name="véhicule")
    justificatif = models.CharField(max_length=255, blank=True)
    commentaire = models.TextField(blank=True)
    saisi_par = models.CharField("saisi par", max_length=100, blank=True)

    class Meta:
        verbose_name = "dépense"

    def __str__(self):
        return f"Dépense {self.id} — {self.categorie}"


class Attribution(models.Model):
    date_debut = models.DateField("date de début")
    date_fin = models.DateField("date de fin", null=True, blank=True)
    chauffeur = models.ForeignKey(Chauffeur, on_delete=models.CASCADE,
                                  related_name="attributions")
    vehicule = models.ForeignKey(Vehicule, on_delete=models.CASCADE,
                                 related_name="attributions", verbose_name="véhicule")
    gelee = models.BooleanField("gelée", default=False,
                                help_text="Ancienne attribution conservée pour l'historique.")
    attribue_par = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL,
                                     verbose_name="attribué par")
    nouveau_chauffeur = models.ForeignKey(Chauffeur, null=True, blank=True,
                                          on_delete=models.SET_NULL,
                                          related_name="reprises", verbose_name="repris par")
    actif = models.BooleanField("en cours", default=True)

    def clean(self):
        if self.date_fin and self.date_debut and self.date_fin < self.date_debut:
            raise ValidationError({"date_fin": "La date de fin précède la date de début."})

    def __str__(self):
        return f"{self.chauffeur} -> {self.vehicule.plaque}"


class Presence(models.Model):
    """Pointage journalier d'un chauffeur, saisi par le service RH."""
    STATUTS = [("Present", "Présent"), ("Retard", "Retard"), ("Absent", "Absent")]
    date = models.DateField()
    nom = models.CharField(max_length=100)
    # PROTECT : on ne perd pas l'historique de pointage en supprimant un chauffeur.
    chauffeur = models.ForeignKey(Chauffeur, null=True, blank=True, on_delete=models.PROTECT,
                                  related_name="presences")
    pointe_par = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name="pointages_saisis", verbose_name="pointé par")
    # Ancien champ (pointage par le compte utilisateur), conservé pour l'historique.
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.PROTECT,
                             verbose_name="compte (ancien pointage)")
    heure_arrivee = models.TimeField("heure d'arrivée", null=True, blank=True)
    heure_depart = models.TimeField("heure de départ", null=True, blank=True)
    statut = models.CharField(max_length=20, choices=STATUTS, default="Present")
    observation = models.CharField(max_length=255, blank=True)

    class Meta:
        verbose_name = "présence"
        ordering = ["-date"]
        constraints = [
            models.UniqueConstraint(fields=["chauffeur", "date"],
                                    name="presence_unique_par_chauffeur_et_jour"),
        ]

    def __str__(self):
        return f"{self.nom} — {self.date:%d/%m/%Y}"


class Conge(models.Model):
    TYPES = [("Annuel", "Annuel"), ("Maladie", "Maladie"), ("Exceptionnel", "Exceptionnel")]
    STATUTS = [("Approuve", "Approuvé"), ("En attente", "En attente"), ("Refuse", "Refusé")]
    DECISIONS = ("Approuve", "Refuse")
    # PROTECT : l'historique des congés est une donnée RH à conserver.
    chauffeur = models.ForeignKey(Chauffeur, on_delete=models.PROTECT)
    date_debut = models.DateField("date de début")
    date_fin = models.DateField("date de fin")
    type_conge = models.CharField("type", max_length=20, choices=TYPES, default="Annuel")
    statut = models.CharField(max_length=20, choices=STATUTS, default="En attente")

    class Meta:
        verbose_name = "congé"

    def clean(self):
        if self.date_fin and self.date_debut and self.date_fin < self.date_debut:
            raise ValidationError({"date_fin": "La date de fin précède la date de début."})

    def __str__(self):
        return f"Congé {self.chauffeur} ({self.get_statut_display()})"


# Attribut pratique : user.role_name accessible dans tous les gabarits.
def _role_name(self):
    return getattr(getattr(self, "profile", None), "role", "")

User.add_to_class("role_name", property(_role_name))
