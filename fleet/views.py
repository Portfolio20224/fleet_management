# -*- coding: utf-8 -*-
"""Vues des 6 espaces métier + accueil et exports CSV."""
import csv
import logging
from datetime import datetime, timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Count, Max, Q, Sum
from django.http import HttpResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.contrib.auth.views import PasswordChangeView
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.dateparse import parse_date

from .decorators import role_required
from .comptes import identifiant_libre, mot_de_passe_provisoire, peut_gerer, roles_attribuables
from .models import (Attribution, Chauffeur, Conge, Depense, Panne, Presence,
                     Profile, Recette, Vehicule)
from .templatetags.filters import monnaie
from .utils import slug_ascii
from .stats import age_revolu, ages_chauffeurs, ages_vehicules, stats_chauffeur

logger = logging.getLogger(__name__)

# Source unique : les étapes du kanban viennent du modèle.
ETAPES = [code for code, _ in Panne.ETAPES]
ETAPE_FINALE = ETAPES[-1]

# Source unique des couleurs de situation (légende HTML + marqueurs de la carte).
SITUATION_COLORS = {
    "En service": "#16a34a",
    "En panne": "#dc2626",
    "En maintenance": "#f59e0b",
    "Gelee": "#64748b",
}

RH_TABS = ("chauffeurs", "pointage", "attributions", "conges", "vehicules", "stats", "ages", "comptes")


# ------------------------------------------------------------------ OUTILS
def aujourdhui():
    return timezone.localdate()


def to_date(s):
    """Convertit 'AAAA-MM-JJ' en date ; renvoie None si vide ou invalide."""
    if not s:
        return None
    try:
        return parse_date(s)
    except ValueError:          # format correct mais date impossible (2026-02-30)
        return None


def to_int(s, default=0):
    """Entier positif ou nul ; lève ValueError si la saisie est invalide."""
    if s in (None, ""):
        return default
    n = int(s)
    if n < 0:
        raise ValueError("montant négatif")
    return n


def valider_image(fichier):
    """Renvoie un message d'erreur, ou None si l'upload est acceptable."""
    if fichier is None:
        return None
    if fichier.size > settings.FLEET_UPLOAD_MAX_BYTES:
        mo = settings.FLEET_UPLOAD_MAX_BYTES // (1024 * 1024)
        return f"Fichier trop volumineux (maximum {mo} Mo)."
    if not (fichier.content_type or "").startswith("image/"):
        return "Le fichier doit être une image."
    # Le type MIME est déclaré par le navigateur : on vérifie le contenu réel.
    try:
        from PIL import Image
        Image.open(fichier).verify()
    except Exception:
        return "Le fichier n'est pas une image valide."
    finally:
        fichier.seek(0)
    return None


def _csv_safe(value):
    """Neutralise l'injection de formules (=, +, -, @) dans Excel.

    Seules les chaînes sont préfixées : un montant numérique négatif reste un nombre.
    """
    if value is None:
        return ""
    if isinstance(value, (bool, int, float)):
        return value
    s = str(value)
    if s[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + s
    return s


class _Echo:
    """Pseudo-fichier : csv.writer écrit, on récupère la ligne pour la streamer."""
    def write(self, value):
        return value


def csv_response(rows, filename):
    """Réponse CSV en streaming, compatible Excel (BOM UTF-8)."""
    writer = csv.writer(_Echo(), delimiter=";")

    def generate():
        yield "﻿"
        for row in rows:
            yield writer.writerow([_csv_safe(v) for v in row])

    response = StreamingHttpResponse(generate(), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def export_csv(queryset, filename):
    """Exporte tous les champs d'un queryset (lecture par paquets via iterator())."""
    fields = queryset.model._meta.fields
    # Les clés étrangères sont exportées par leur libellé (ex. nom du chauffeur) :
    # select_related évite une requête par ligne et par clé.
    fks = [f.name for f in fields if f.is_relation]
    queryset = queryset.select_related(*fks)

    def rows():
        yield [f.name for f in fields]
        for obj in queryset.iterator(chunk_size=500):
            yield [getattr(obj, f.name) for f in fields]

    return csv_response(rows(), filename)


# ------------------------------------------------------------------ MOT DE PASSE
class ChangerMotDePasse(PasswordChangeView):
    """Chaque employé change son propre mot de passe (obligatoire après un mot de passe provisoire)."""
    template_name = "mot_de_passe.html"
    success_url = reverse_lazy("fleet:home")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["premiere_fois"] = getattr(getattr(self.request.user, "profile", None),
                                       "doit_changer_mdp", False)
        return ctx

    def form_valid(self, form):
        reponse = super().form_valid(form)   # garde la session ouverte avec le nouveau mot de passe
        Profile.objects.filter(user=self.request.user).update(doit_changer_mdp=False)
        messages.success(self.request, "Votre mot de passe a été changé.")
        return reponse


# ------------------------------------------------------------------ TECHNIQUE (santé, fichiers)
def sante(request):
    """Contrôle de santé pour l'hébergeur : répond 200 si l'application et la base répondent."""
    from django.db import connection
    try:
        with connection.cursor() as c:
            c.execute("SELECT 1")
    except Exception:
        logger.exception("Contrôle de santé : base de données injoignable")
        return HttpResponse("base de données injoignable", status=503, content_type="text/plain")
    return HttpResponse("ok", content_type="text/plain")


@login_required
def media_protege(request, chemin):
    """Sert un fichier envoyé (capture, photo) aux seuls utilisateurs connectés.

    Avant, /media/ n'était servi qu'en DEBUG et sans contrôle : une capture de versement
    était lisible par quiconque connaissait l'adresse. `serve` refuse les chemins qui
    sortent de MEDIA_ROOT. Suffisant pour le volume de l'application ; au-delà, déléguer
    à un stockage objet (S3, R2…) avec des liens temporaires.
    """
    from django.views.static import serve
    reponse = serve(request, chemin, document_root=settings.MEDIA_ROOT)
    reponse["Cache-Control"] = "private, max-age=3600"
    return reponse


# ------------------------------------------------------------------ ACCUEIL
@login_required
def home(request):
    return render(request, "home.html")


# ------------------------------------------------------------------ PERCEPTEUR
class RecetteEnDouble(Exception):
    """Le chauffeur a déjà une recette dans la fenêtre de 12 heures."""
    def __init__(self, recette):
        self.recette = recette
        super().__init__(f"Recette {recette.pk} déjà saisie")


def _fmt_heure(dt):
    """Heure locale lisible ; précise le jour si ce n'est pas aujourd'hui."""
    local = timezone.localtime(dt)
    if local.date() == aujourdhui():
        return local.strftime("%H:%M")
    return local.strftime("%d/%m à %H:%M")


def attributions_saisissables(auj):
    """Attributions actives à ce jour, pour un chauffeur actif : base de la saisie."""
    return (Attribution.objects.filter(actif=True, date_debut__lte=auj, chauffeur__statut="Actif")
            .select_related("chauffeur", "vehicule").order_by("chauffeur__nom", "chauffeur__prenom"))


def recettes_recentes(maintenant):
    """{chauffeur_id: dernière recette} saisie dans les 12 dernières heures."""
    depuis = maintenant - Recette.DELAI_ENTRE_RECETTES
    dernieres = {}
    for r in (Recette.objects.filter(saisie_le__gt=depuis)
              .select_related("percepteur").order_by("saisie_le")):
        dernieres[r.chauffeur_id] = r
    return dernieres


def _creer_recette(auj, chauffeur, **champs):
    """Crée la recette avec le prochain numéro d'ordre du jour, sans doublon.

    - Règle des 12 heures : la ligne du chauffeur est verrouillée
      (select_for_update) pendant la vérification, pour que deux percepteurs
      qui valident en même temps ne créent pas deux recettes.
    - Numéro d'ordre : contrainte unique (date, num_ordre) + nouvel essai en
      cas de collision (SQLite ignore select_for_update).
    """
    for _ in range(3):
        try:
            with transaction.atomic():
                Chauffeur.objects.select_for_update().filter(pk=chauffeur.pk).exists()
                maintenant = timezone.now()
                existante = (Recette.objects
                             .filter(chauffeur=chauffeur,
                                     saisie_le__gt=maintenant - Recette.DELAI_ENTRE_RECETTES)
                             .select_related("percepteur").order_by("-saisie_le").first())
                if existante:
                    raise RecetteEnDouble(existante)
                max_ordre = (Recette.objects.select_for_update()
                             .filter(date=auj).aggregate(m=Max("num_ordre"))["m"] or 0)
                return Recette.objects.create(date=auj, saisie_le=maintenant,
                                              num_ordre=max_ordre + 1,
                                              chauffeur=chauffeur, **champs)
        except IntegrityError:
            continue
    raise IntegrityError("Impossible d'attribuer un numéro d'ordre.")


def _message_double(chauffeur, r):
    prochaine = _fmt_heure(r.saisie_le + Recette.DELAI_ENTRE_RECETTES)
    par = r.percepteur.get_full_name() or r.percepteur.username
    return (f"Recette refusée : {chauffeur} a déjà une recette saisie à "
            f"{_fmt_heure(r.saisie_le)} (n°{r.num_ordre}, par {par}). "
            f"Nouvelle saisie possible à partir de {prochaine}.")


@role_required("PERCEPTEUR", "DG")
def percepteur(request):
    auj = aujourdhui()
    est_dg = request.user.role_name == "DG"
    du_jour = Recette.objects.filter(date=auj).select_related("chauffeur", "vehicule")
    # Un percepteur clôture ses propres recettes ; la DG peut tout clôturer.
    a_cloturer = du_jour.filter(cloturee=False)
    if not est_dg:
        a_cloturer = a_cloturer.filter(percepteur=request.user)

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "recette":
            ch = get_object_or_404(Chauffeur, pk=request.POST.get("chauffeur"), statut="Actif")
            # Le véhicule vient de l'attribution en cours, jamais d'un choix libre.
            vehicules_ch = {a.vehicule_id: a.vehicule
                            for a in attributions_saisissables(auj).filter(chauffeur=ch)}
            if not vehicules_ch:
                messages.error(request, f"{ch} n'a aucun véhicule attribué : saisie impossible.")
                return redirect("fleet:percepteur")
            ve_id = request.POST.get("vehicule")
            if len(vehicules_ch) == 1 and not ve_id:
                ve = next(iter(vehicules_ch.values()))
            else:
                ve = vehicules_ch.get(int(ve_id)) if (ve_id or "").isdigit() else None
            if ve is None:
                messages.error(request, f"Ce véhicule n'est pas attribué à {ch}.")
                return redirect("fleet:percepteur")
            try:
                verse = to_int(request.POST.get("montant_verse"))
                fixe = to_int(request.POST.get("montant_fixe"))
            except (TypeError, ValueError):
                messages.error(request, "Montant invalide : saisissez un nombre entier positif.")
                return redirect("fleet:percepteur")
            capture = request.FILES.get("capture")
            erreur = valider_image(capture)
            if erreur:
                messages.error(request, erreur)
                return redirect("fleet:percepteur")
            try:
                r = _creer_recette(
                    auj, ch, vehicule=ve, percepteur=request.user,
                    montant_verse=verse, montant_fixe=fixe,
                    observation=request.POST.get("observation", "").strip(),
                    capture=capture or "",
                    saisi_par=request.user.get_full_name() or request.user.username)
            except RecetteEnDouble as e:
                messages.error(request, _message_double(ch, e.recette))
                return redirect("fleet:percepteur")
            messages.success(request, f"Recette n°{r.num_ordre} enregistrée : {ch} — {ve.plaque}.")
            return redirect("fleet:percepteur")

        if action == "cloturer":
            ids = request.POST.getlist("recette_ids")
            n = a_cloturer.filter(pk__in=[i for i in ids if i.isdigit()]).update(cloturee=True)
            if n:
                messages.success(request, f"{n} recette(s) clôturée(s).")
            else:
                messages.warning(request, "Aucune recette sélectionnée.")
            return redirect("fleet:percepteur")

    totaux = du_jour.aggregate(verse=Sum("montant_verse"), fixe=Sum("montant_fixe"),
                               nb=Count("id"))

    # Liste de saisie : uniquement les chauffeurs ayant un véhicule attribué.
    # Ceux qui ont déjà une recette dans les 12 h restent visibles, mais grisés.
    attributions = list(attributions_saisissables(auj))
    recentes = recettes_recentes(timezone.now())
    chauffeurs_saisie, vehicules_saisie = {}, []
    for a in attributions:
        c = chauffeurs_saisie.setdefault(a.chauffeur_id, {"obj": a.chauffeur, "vehicules": [],
                                                          "bloque": None})
        c["vehicules"].append(a.vehicule_id)
        vehicules_saisie.append({"obj": a.vehicule, "chauffeur_id": a.chauffeur_id})
        r = recentes.get(a.chauffeur_id)
        if r:
            c["bloque"] = {"a": _fmt_heure(r.saisie_le),
                           "jusqua": _fmt_heure(r.saisie_le + Recette.DELAI_ENTRE_RECETTES)}
    chauffeurs_saisie = list(chauffeurs_saisie.values())
    for c in chauffeurs_saisie:
        c["vehicules_csv"] = ",".join(str(v) for v in c["vehicules"])

    context = {
        "missions": (Attribution.objects.filter(actif=True, date_debut__lte=auj)
                     .select_related("chauffeur", "vehicule")),
        "chauffeurs_saisie": chauffeurs_saisie,
        "vehicules_saisie": vehicules_saisie,
        "nb_saisissables": sum(1 for c in chauffeurs_saisie if not c["bloque"]),
        "du_jour": du_jour,
        "nb_du_jour": totaux["nb"],
        "total_verse": totaux["verse"] or 0,
        "total_fixe": totaux["fixe"] or 0,
        "ecart": (totaux["verse"] or 0) - (totaux["fixe"] or 0),
        "a_cloturer": a_cloturer,
        "ids_a_cloturer": set(a_cloturer.values_list("id", flat=True)),
        "montant_defaut": settings.FLEET_MONTANT_FIXE_DEFAUT,
    }
    return render(request, "percepteur.html", context)


# ------------------------------------------------------------------ CHAUFFEUR
@role_required("CHAUFFEUR", "DG")
def chauffeur(request):
    auj = aujourdhui()
    profile = getattr(request.user, "profile", None)
    moi = getattr(profile, "chauffeur", None)
    attribution = (Attribution.objects.filter(chauffeur=moi, actif=True)
                   .select_related("vehicule").first() if moi else None)
    vehicule = attribution.vehicule if attribution else None

    # Un chauffeur déclare une panne sur SON véhicule ; la DG (sans fiche
    # chauffeur) peut déclarer sur n'importe quel véhicule.
    if request.user.role_name == "DG":
        vehicules_declarables = Vehicule.objects.all()
    elif vehicule:
        vehicules_declarables = Vehicule.objects.filter(pk=vehicule.pk)
    else:
        vehicules_declarables = Vehicule.objects.none()

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "panne":
            ve = get_object_or_404(vehicules_declarables, pk=request.POST.get("vehicule"))
            description = request.POST.get("description", "").strip()
            priorite = request.POST.get("priorite")
            if not description:
                messages.error(request, "Décrivez la panne avant de l'envoyer.")
                return redirect("fleet:chauffeur")
            if priorite not in dict(Panne.PRIORITES):
                priorite = "Moyenne"
            photo = request.FILES.get("photo")
            erreur = valider_image(photo)
            if erreur:
                messages.error(request, erreur)
                return redirect("fleet:chauffeur")
            Panne.objects.create(date_declaration=auj, vehicule=ve, declaree_par=moi,
                                 description=description, priorite=priorite,
                                 photo=photo or "")
            messages.success(request, "Panne transmise au service technique.")
            return redirect("fleet:chauffeur")

    context = {
        "moi": moi,
        # Le pointage est saisi par la RH : le chauffeur le consulte seulement.
        "presence": Presence.objects.filter(chauffeur=moi, date=auj).first() if moi else None,
        "presences": (Presence.objects.filter(chauffeur=moi).select_related("pointe_par")[:10]
                      if moi else []),
        "stats": stats_chauffeur(moi, auj) if moi else None,
        "attribution": attribution,
        "vehicule": vehicule,
        "vehicules": vehicules_declarables,
        "priorites": Panne.PRIORITES,
        "historique": (Attribution.objects.filter(chauffeur=moi)
                       .select_related("vehicule").order_by("-date_debut") if moi else []),
    }
    return render(request, "chauffeur.html", context)


# ------------------------------------------------------------------ TECHNIQUE
@role_required("TECHNIQUE", "DG")
def technique(request):
    if request.method == "POST":
        panne = get_object_or_404(Panne, pk=request.POST.get("panne_id"))
        i = ETAPES.index(panne.statut) if panne.statut in ETAPES else len(ETAPES) - 1
        if i < len(ETAPES) - 1:
            panne.statut = ETAPES[i + 1]
            panne.save(update_fields=["statut"])
            messages.success(request,
                             f"Panne {panne.id} passée à « {panne.get_statut_display()} ».")
        return redirect("fleet:technique")

    # 1 requête pour les compteurs, 1 requête pour toutes les cartes.
    stats = Panne.objects.aggregate(
        total=Count("id"),
        terminees=Count("id", filter=Q(statut=ETAPE_FINALE)),
        critiques=Count("id", filter=Q(priorite="Critique") & ~Q(statut=ETAPE_FINALE)),
    )
    par_etape = {e: [] for e in ETAPES}
    for p in (Panne.objects.select_related("vehicule", "declaree_par")
              .order_by("-date_declaration")):
        par_etape.setdefault(p.statut, []).append(p)

    libelles = dict(Panne.ETAPES)
    colonnes = [{
        "code": e,
        "libelle": libelles[e],
        "suivante": libelles[ETAPES[i + 1]] if i + 1 < len(ETAPES) else "",
        "pannes": par_etape[e],
    } for i, e in enumerate(ETAPES)]

    total = stats["total"]
    context = {
        "colonnes": colonnes,
        "etape_finale": ETAPE_FINALE,
        "ouvertes": total - stats["terminees"],
        "critiques": stats["critiques"],
        "terminees": stats["terminees"],
        "taux": round(100 * stats["terminees"] / total) if total else 0,
    }
    return render(request, "technique.html", context)


# ------------------------------------------------------------------ RH
def _heure(s):
    """'HH:MM' -> time, None si vide ; lève ValueError si invalide."""
    if not s:
        return None
    return datetime.strptime(s, "%H:%M").time()


def _pointer(request, auj):
    """Pointage du jour par la RH : arrivée, départ ou absence d'un chauffeur."""
    ch = get_object_or_404(Chauffeur, pk=request.POST.get("chauffeur"), statut="Actif")
    quoi = request.POST.get("quoi")
    maintenant = timezone.localtime().time().replace(second=0, microsecond=0)
    try:
        heure = _heure(request.POST.get("heure")) or maintenant
    except ValueError:
        return messages.ERROR, "Heure invalide (format HH:MM)."
    if heure > maintenant:
        return messages.ERROR, "On ne peut pas pointer une heure future."
    p = Presence.objects.filter(chauffeur=ch, date=auj).first()
    limite = _heure(settings.FLEET_HEURE_RETARD)
    if not p and Conge.objects.filter(chauffeur=ch, statut="Approuve",
                                      date_debut__lte=auj, date_fin__gte=auj).exists():
        return messages.ERROR, f"{ch} est en congé approuvé aujourd'hui : pas de pointage."

    if quoi == "arrivee":
        if p and p.heure_arrivee:
            return messages.WARNING, f"Arrivée de {ch} déjà pointée à {p.heure_arrivee:%H:%M}."
        p = p or Presence(chauffeur=ch, date=auj, nom=str(ch))
        p.heure_arrivee = heure
        p.statut = "Retard" if heure > limite else "Present"
        p.observation = "" if p.statut == "Present" else p.observation
        p.pointe_par = request.user
        p.save()
        return messages.SUCCESS, f"Arrivée de {ch} pointée à {heure:%H:%M} ({p.get_statut_display()})."

    if quoi == "depart":
        if not p or not p.heure_arrivee:
            return messages.ERROR, f"Pointez d'abord l'arrivée de {ch}."
        if p.heure_depart:
            return messages.WARNING, f"Départ de {ch} déjà pointé à {p.heure_depart:%H:%M}."
        if heure <= p.heure_arrivee:
            return messages.ERROR, f"Le départ doit être après l'arrivée ({p.heure_arrivee:%H:%M})."
        p.heure_depart = heure
        p.pointe_par = request.user
        p.save(update_fields=["heure_depart", "pointe_par"])
        return messages.SUCCESS, f"Départ de {ch} pointé à {heure:%H:%M}."

    if quoi == "absent":
        if p and p.heure_arrivee:
            return messages.ERROR, f"{ch} a déjà une arrivée pointée : corrigez via l'administration."
        Presence.objects.update_or_create(
            chauffeur=ch, date=auj,
            defaults={"nom": str(ch), "statut": "Absent", "pointe_par": request.user,
                      "observation": request.POST.get("observation", "").strip()[:255]})
        return messages.SUCCESS, f"{ch} marqué absent aujourd'hui."

    return messages.ERROR, "Type de pointage inconnu."


def _montrer_mdp(request, user, mdp):
    """Le mot de passe provisoire est affiché UNE fois, sur la page suivante.

    Il passe par la session (stockée côté serveur), pas par les messages, dont le
    stockage peut être un cookie lisible par le navigateur.
    """
    request.session["mdp_provisoire"] = {"identifiant": user.username,
                                         "nom": user.first_name or user.username, "mdp": mdp}


def _gerer_compte(request, action):
    acteur = request.user
    if action == "creer_compte":
        P = request.POST
        role = P.get("role")
        if role not in dict(roles_attribuables(acteur)):
            return messages.ERROR, "Rôle non autorisé."
        fiche = None
        if role == Profile.Roles.CHAUFFEUR:
            fiche = get_object_or_404(Chauffeur, pk=P.get("chauffeur"))
            if Profile.objects.filter(chauffeur=fiche).exists():
                return messages.ERROR, f"{fiche} a déjà un compte."
            prenom, nom, tel = fiche.prenom, fiche.nom, fiche.tel
        else:
            prenom = " ".join(P.get("prenom", "").split())
            nom = " ".join(P.get("nom", "").split())
            tel = P.get("tel", "").strip()
            if not prenom or not nom:
                return messages.ERROR, "Nom et prénom sont obligatoires."
        ident = P.get("identifiant", "").strip().lower()
        if ident:
            try:
                User.username_validator(ident)
            except ValidationError:
                return messages.ERROR, "Identifiant invalide : lettres, chiffres et . - _ @ + uniquement."
            if User.objects.filter(username__iexact=ident).exists():
                return messages.ERROR, f"L'identifiant « {ident} » est déjà pris."
        else:
            ident = identifiant_libre(prenom, nom)
        mdp = mot_de_passe_provisoire()
        with transaction.atomic():
            u = User.objects.create_user(username=ident, password=mdp,
                                         first_name=f"{nom} {prenom}"[:150],
                                         email=getattr(fiche, "email", "") or "")
            Profile.objects.create(user=u, role=role, chauffeur=fiche, tel=tel,
                                   service=dict(Profile.Roles.choices)[role],
                                   doit_changer_mdp=True)
        _montrer_mdp(request, u, mdp)
        return messages.SUCCESS, f"Compte créé pour {u.first_name}."

    cible = get_object_or_404(User, pk=request.POST.get("user_id"))
    if not peut_gerer(acteur, cible):
        return messages.ERROR, "Ce compte ne peut pas être modifié depuis l'espace RH."
    if action == "reinit_mdp":
        mdp = mot_de_passe_provisoire()
        cible.set_password(mdp)
        cible.save(update_fields=["password"])   # déconnecte aussi ses sessions ouvertes
        Profile.objects.filter(user=cible).update(doit_changer_mdp=True)
        _montrer_mdp(request, cible, mdp)
        return messages.SUCCESS, f"Mot de passe de {cible.first_name or cible.username} réinitialisé."
    cible.is_active = action == "activer"
    cible.save(update_fields=["is_active"])
    etat = "réactivé" if cible.is_active else "désactivé (historique conservé)"
    return messages.SUCCESS, f"Compte de {cible.first_name or cible.username} {etat}."


def _rh_post(request, action, auj):
    """Traite une action RH. Renvoie (niveau, message)."""
    if action == "add_chauffeur":
        nom = request.POST.get("nom", "").strip()
        prenom = request.POST.get("prenom", "").strip()
        permis = request.POST.get("permis", "B")
        if not nom or not prenom:
            return messages.ERROR, "Nom et prénom sont obligatoires."
        if permis not in ("B", "C", "D", "E"):
            return messages.ERROR, "Catégorie de permis invalide."
        naissance = to_date(request.POST.get("date_naissance"))
        expiration = to_date(request.POST.get("date_expiration_permis"))
        if naissance and age_revolu(naissance, auj) < 18:
            return messages.ERROR, "Date de naissance invalide : le chauffeur doit avoir au moins 18 ans."
        if not expiration:
            return messages.ERROR, "La date d'expiration du permis est obligatoire."
        Chauffeur.objects.create(
            nom=nom, prenom=prenom,
            email=f"{slug_ascii(prenom)}.{slug_ascii(nom)}@fleet.local",
            tel=request.POST.get("tel", "").strip(), permis=permis,
            date_naissance=naissance, date_expiration_permis=expiration,
            date_embauche=to_date(request.POST.get("date_embauche")))
        if expiration < auj:
            return messages.WARNING, (f"Chauffeur {nom} {prenom} ajouté, mais son permis a expiré "
                                      f"le {expiration:%d/%m/%Y} : il apparaîtra dans les alertes.")
        return messages.SUCCESS, f"Chauffeur {nom} {prenom} ajouté."

    if action == "pointage":
        return _pointer(request, auj)

    if action in ("creer_compte", "reinit_mdp", "activer", "desactiver"):
        return _gerer_compte(request, action)

    if action == "attribution":
        ch = get_object_or_404(Chauffeur, pk=request.POST.get("chauffeur"))
        ve = get_object_or_404(Vehicule, pk=request.POST.get("vehicule"),
                               situation__in=["En service", "Gelee"])
        date_debut = to_date(request.POST.get("date_debut")) or auj
        # Tout ou rien : l'ancienne attribution n'est gelée que si la nouvelle est créée.
        with transaction.atomic():
            ancienne = (Attribution.objects.select_for_update()
                        .filter(vehicule=ve, actif=True).first())
            if ancienne:
                ancienne.actif = False
                ancienne.gelee = True
                ancienne.date_fin = auj
                ancienne.nouveau_chauffeur = ch
                ancienne.save()
            Attribution.objects.create(date_debut=date_debut, chauffeur=ch, vehicule=ve,
                                       attribue_par=request.user)
        return messages.SUCCESS, f"Véhicule {ve.plaque} attribué à {ch}."

    if action == "add_conge":
        ch = get_object_or_404(Chauffeur, pk=request.POST.get("chauffeur"))
        type_conge = request.POST.get("type_conge")
        if type_conge not in dict(Conge.TYPES):
            return messages.ERROR, "Type de congé invalide."
        conge = Conge(chauffeur=ch, type_conge=type_conge,
                      date_debut=to_date(request.POST.get("date_debut")),
                      date_fin=to_date(request.POST.get("date_fin")))
        if not conge.date_debut or not conge.date_fin:
            return messages.ERROR, "Dates de congé manquantes ou invalides."
        try:
            conge.full_clean()
        except ValidationError as e:
            return messages.ERROR, " ".join(e.messages)
        conge.save()
        return messages.SUCCESS, "Demande de congé soumise (en attente)."

    if action == "decision":
        decision = request.POST.get("decision")
        if decision not in Conge.DECISIONS:
            return messages.ERROR, "Décision invalide."
        c = get_object_or_404(Conge, pk=request.POST.get("conge_id"), statut="En attente")
        c.statut = decision
        c.save(update_fields=["statut"])
        return messages.SUCCESS, f"Demande {c.id} : {c.get_statut_display()}."

    return messages.ERROR, "Action inconnue."


@role_required("RH", "DG")
def rh(request):
    auj = aujourdhui()
    tab = request.POST.get("tab") or request.GET.get("tab")
    if tab not in RH_TABS:
        tab = RH_TABS[0]

    if request.method == "POST":
        niveau, texte = _rh_post(request, request.POST.get("action"), auj)
        messages.add_message(request, niveau, texte)
        return redirect(f"{reverse('fleet:rh')}?tab={tab}")

    def jours(d):
        return (d - auj).days if d else None

    vehicules = [{"obj": v, "j_ct": jours(v.prochain_ct), "j_assu": jours(v.assurance_expire)}
                 for v in Vehicule.objects.all()]
    sel = request.GET.get("chauffeur") or ""
    chauffeur_sel = Chauffeur.objects.filter(pk=sel).first() if sel.isdigit() else None
    nb = Chauffeur.objects.aggregate(
        actifs=Count("id", filter=Q(statut="Actif")),
        conge=Count("id", filter=Q(statut="En conge")),
        suspendus=Count("id", filter=Q(statut="Suspendu")),
    )
    context = {
        "tab": tab,
        "chauffeurs": Chauffeur.objects.all(),
        "nb_actifs": nb["actifs"],
        "nb_conge": nb["conge"],
        "nb_suspendus": nb["suspendus"],
        "attributions": (Attribution.objects.filter(actif=True)
                         .select_related("chauffeur", "vehicule")),
        "vehicules_dispo": Vehicule.objects.filter(situation__in=["En service", "Gelee"]),
        "conges": Conge.objects.select_related("chauffeur"),
        "conges_attente": Conge.objects.filter(statut="En attente").select_related("chauffeur"),
        "types_conge": Conge.TYPES,
        "vehicules": vehicules,
        "pointage": _lignes_pointage(auj),
        "heure_retard": settings.FLEET_HEURE_RETARD,
        "chauffeur_sel": chauffeur_sel,
        "stats": stats_chauffeur(chauffeur_sel, auj) if chauffeur_sel else None,
        "ages": ages_chauffeurs(auj),
        "comptes": _lignes_comptes(request.user),
        "roles_attribuables": roles_attribuables(request.user),
        "chauffeurs_sans_compte": Chauffeur.objects.exclude(statut="Suspendu")
                                  .filter(profile__isnull=True).order_by("nom", "prenom"),
        "mdp_provisoire": request.session.pop("mdp_provisoire", None),
    }
    return render(request, "rh.html", context)


def _lignes_comptes(acteur):
    users = (User.objects.select_related("profile", "profile__chauffeur")
             .order_by("-is_active", "profile__role", "first_name"))
    return [{"obj": u, "gerable": peut_gerer(acteur, u)} for u in users]


def _lignes_pointage(auj):
    """Une ligne par chauffeur actif : son pointage du jour, son véhicule, s'il est en congé."""
    presences = {p.chauffeur_id: p for p in Presence.objects.filter(date=auj).exclude(chauffeur=None)}
    vehicules = {a.chauffeur_id: a.vehicule for a in
                 Attribution.objects.filter(actif=True).select_related("vehicule")}
    en_conge = set(Conge.objects.filter(statut="Approuve", date_debut__lte=auj, date_fin__gte=auj)
                   .values_list("chauffeur_id", flat=True))
    return [{"obj": c, "presence": presences.get(c.pk), "vehicule": vehicules.get(c.pk),
             "en_conge": c.pk in en_conge}
            for c in Chauffeur.objects.filter(statut="Actif").order_by("nom", "prenom")]


# ------------------------------------------------------------------ FINANCE
def _ajouter_depense(request, auj):
    d = to_date(request.POST.get("date"))
    categorie = " ".join(request.POST.get("categorie", "").split())[:50]
    type_dep = request.POST.get("type_dep") or "Operationnelle"
    if not d:
        return messages.ERROR, "Date invalide."
    if d > auj:
        return messages.ERROR, "Une dépense ne peut pas être datée dans le futur."
    if not categorie:
        return messages.ERROR, "La catégorie est obligatoire."
    if type_dep not in dict(Depense.TYPES):
        return messages.ERROR, "Type de dépense invalide."
    try:
        montant = to_int(request.POST.get("montant"), default=None)
    except (TypeError, ValueError):
        montant = None
    if not montant:
        return messages.ERROR, "Montant invalide : saisissez un nombre entier supérieur à 0."
    # Réutilise l'orthographe d'une catégorie existante (« carburant » -> « Carburant »).
    existante = (Depense.objects.filter(categorie__iexact=categorie)
                 .values_list("categorie", flat=True).first())
    dep = Depense.objects.create(
        date=d, type_dep=type_dep, categorie=existante or categorie, montant=montant,
        commentaire=request.POST.get("commentaire", "").strip(),
        saisi_par=request.user.get_full_name() or request.user.username)
    return messages.SUCCESS, (f"Dépense enregistrée : {dep.categorie}, "
                              f"{monnaie(montant)} le {d:%d/%m/%Y}.")


@role_required("TRESORIER", "DG")
def finance(request):
    auj = aujourdhui()
    export = request.GET.get("export")
    if export == "recettes":
        return export_csv(Recette.objects.order_by("date", "num_ordre"), "recettes.csv")
    if export == "depenses":
        return export_csv(Depense.objects.order_by("date", "id"), "depenses.csv")

    if request.method == "POST" and request.POST.get("action") == "add_depense":
        niveau, texte = _ajouter_depense(request, auj)
        messages.add_message(request, niveau, texte)
        return redirect("fleet:finance")

    il_y_a_7j = auj - timedelta(days=7)
    mois_courant = Q(date__year=auj.year, date__month=auj.month)

    r = Recette.objects.aggregate(
        jour=Sum("montant_verse", filter=Q(date=auj)),
        sem=Sum("montant_verse", filter=Q(date__gte=il_y_a_7j)),
        mois=Sum("montant_verse", filter=mois_courant),
        total=Sum("montant_verse"),
    )
    d = Depense.objects.aggregate(mois=Sum("montant", filter=mois_courant), total=Sum("montant"))

    recettes_jour = (Recette.objects.values("date")
                     .annotate(total=Sum("montant_verse")).order_by("date"))
    dep_par_cat = (Depense.objects.filter(mois_courant).values("categorie")
                   .annotate(total=Sum("montant")).order_by("-total"))
    libelles_type = dict(Depense.TYPES)
    dep_par_type = Depense.objects.values("type_dep").annotate(total=Sum("montant"))

    total_r = r["total"] or 0
    total_d = d["total"] or 0
    solde = total_r - total_d

    context = {
        "r_jour_total": r["jour"] or 0,
        "r_sem_total": r["sem"] or 0,
        "r_mois_total": r["mois"] or 0,
        "d_mois_total": d["mois"] or 0,
        # Sérialisées par {{ …|json_script }} dans le gabarit (pas de |safe).
        "chart_data": {
            "dates": [x["date"].strftime("%d/%m") for x in recettes_jour],
            "totaux": [x["total"] for x in recettes_jour],
            "cat": [x["categorie"] for x in dep_par_cat],
            "cat_montants": [x["total"] for x in dep_par_cat],
            "type": [libelles_type.get(x["type_dep"], x["type_dep"]) for x in dep_par_type],
            "type_montants": [x["total"] for x in dep_par_type],
        },
        "total_r": total_r,
        "total_d": total_d,
        "solde": solde,
        "categories": (Depense.objects.order_by("categorie")
                       .values_list("categorie", flat=True).distinct()),
        "types_depense": Depense.TYPES,
        "auj": auj,
        "dernieres_depenses": Depense.objects.order_by("-date", "-id")[:8],
        # Marge nette = part des recettes qui reste après dépenses, bornée à [0, 100].
        "marge": min(max(solde / total_r * 100 if total_r else 0, 0), 100),
    }
    return render(request, "finance.html", context)


# ------------------------------------------------------------------ DG
def _alertes(auj):
    """Alertes calculées à la volée, critiques en premier."""
    alertes = []
    for v in Vehicule.objects.all():
        if v.assurance_expire:
            j = (v.assurance_expire - auj).days
            if j < 0:
                alertes.append(("critique", f"Assurance EXPIRÉE depuis {-j} j — {v.plaque} ({v.marque} {v.modele})"))
            elif j <= 15:
                alertes.append(("warning", f"Assurance sous 15 jours ({j} j restants) — {v.plaque}"))
        if v.prochain_ct:
            j = (v.prochain_ct - auj).days
            if j < 0:
                alertes.append(("critique", f"Contrôle technique DÉPASSÉ de {-j} j — {v.plaque}"))
            elif j <= 15:
                alertes.append(("warning", f"CT sous 15 jours ({j} j restants) — {v.plaque}"))
    for ch in Chauffeur.objects.exclude(date_expiration_permis=None):
        j = (ch.date_expiration_permis - auj).days
        if j < 0:
            alertes.append(("critique", f"Permis EXPIRÉ — {ch.prenom} {ch.nom} ({ch.id})"))
        elif j <= 30:
            alertes.append(("warning", f"Permis expire dans {j} j — {ch.prenom} {ch.nom}"))
    for p in (Panne.objects.exclude(statut=ETAPE_FINALE).filter(priorite="Critique")
              .select_related("vehicule")):
        alertes.append(("critique", f"Panne CRITIQUE ouverte — {p.description} ({p.vehicule.plaque})"))
    alertes.sort(key=lambda a: a[0] != "critique")   # tri stable : critiques d'abord
    return alertes


def _ajouter_vehicule(request, auj):
    P = request.POST
    plaque = " ".join(P.get("plaque", "").upper().split())
    marque, modele = P.get("marque", "").strip(), P.get("modele", "").strip()
    if not plaque or not marque or not modele:
        return messages.ERROR, "Plaque, marque et modèle sont obligatoires."
    if Vehicule.objects.filter(plaque__iexact=plaque).exists():
        return messages.ERROR, f"La plaque {plaque} existe déjà."
    try:
        annee = to_int(P.get("annee_fabrication"), default=None)
        km = to_int(P.get("kilometrage"), default=0)
    except (TypeError, ValueError):
        return messages.ERROR, "Année ou kilométrage invalide."
    acquisition = to_date(P.get("date_acquisition"))
    if not acquisition:
        return messages.ERROR, "La date d'acquisition est obligatoire (elle sert au calcul de l'âge du parc)."
    if acquisition > auj:
        return messages.ERROR, "La date d'acquisition ne peut pas être dans le futur."
    if annee and not 1980 <= annee <= auj.year + 1:
        return messages.ERROR, "Année de fabrication invalide."
    if annee and annee > acquisition.year + 1:
        return messages.ERROR, "L'année de fabrication est postérieure à l'acquisition."
    v = Vehicule.objects.create(
        plaque=plaque, marque=marque, modele=modele,
        numero_chassis=P.get("numero_chassis", "").strip(),
        carburant=P.get("carburant") or "Diesel", annee_fabrication=annee,
        date_acquisition=acquisition, type_vehicule=P.get("type_vehicule", "").strip(),
        categorie=P.get("categorie", "").strip(), kilometrage=km,
        prochain_ct=to_date(P.get("prochain_ct")), assurance_expire=to_date(P.get("assurance_expire")))
    return messages.SUCCESS, (f"Véhicule {v.plaque} ajouté (en service). "
                              "Attribuez-le à un chauffeur depuis l'espace RH.")


@role_required("DG")
def dg(request):
    auj = aujourdhui()
    if request.method == "POST" and request.POST.get("action") == "add_vehicule":
        niveau, texte = _ajouter_vehicule(request, auj)
        messages.add_message(request, niveau, texte)
        return redirect(f"{reverse('fleet:dg')}#parc")
    mois = request.GET.get("mois") or auj.strftime("%Y-%m")
    try:
        annee, mois_num = int(mois[:4]), int(mois[5:7])
        if not 1 <= mois_num <= 12:
            raise ValueError
    except ValueError:
        mois, annee, mois_num = auj.strftime("%Y-%m"), auj.year, auj.month

    r_mois = Recette.objects.filter(date__year=annee, date__month=mois_num)
    recap = (r_mois.values("date")
             .annotate(verse=Sum("montant_verse"), fixe=Sum("montant_fixe"))
             .order_by("date"))

    if request.GET.get("export") == "rapport":
        rows = [["Date", "Montant versé", "Montant fixe"]]
        rows += [[x["date"].strftime("%d/%m/%Y"), x["verse"], x["fixe"]] for x in recap]
        return csv_response(rows, f"rapport_{annee}-{mois_num:02d}.csv")

    totaux_mois = r_mois.aggregate(ca=Sum("montant_verse"), nb=Count("id"))
    ca = totaux_mois["ca"] or 0
    dep = (Depense.objects.filter(date__year=annee, date__month=mois_num)
           .aggregate(t=Sum("montant"))["t"] or 0)
    alertes = _alertes(auj)

    pres = Presence.objects.filter(date=auj).aggregate(
        nb=Count("id"), presents=Count("id", filter=~Q(statut="Absent")))
    taux = round(100 * pres["presents"] / pres["nb"]) if pres["nb"] else 0

    vehicules = list(Vehicule.objects.all())
    vehicules_carte = [
        {"plaque": v.plaque, "situation": v.situation,
         "situation_libelle": v.get_situation_display(),
         "lat": v.latitude, "lon": v.longitude, "marque": v.marque, "modele": v.modele}
        for v in vehicules]
    libelles_situation = dict(Vehicule.SITUATIONS)

    top = (r_mois.values("vehicule__plaque")
           .annotate(t=Sum("montant_verse")).order_by("-t").first())

    context = {
        "mois": f"{annee}-{mois_num:02d}",
        "mois_dispo": [(d.strftime("%Y-%m"), d.strftime("%m/%Y"))
                       for d in Recette.objects.dates("date", "month")],
        "ca_mois": ca,
        "dep_mois": dep,
        "resultat": ca - dep,
        "nb_recettes": totaux_mois["nb"],
        "r_jour_total": Recette.objects.filter(date=auj)
                        .aggregate(t=Sum("montant_verse"))["t"] or 0,
        "nb_vehicules_service": sum(1 for v in vehicules if v.situation == "En service"),
        "nb_vehicules": len(vehicules),
        "pannes_ouvertes": Panne.objects.exclude(statut=ETAPE_FINALE).count(),
        "taux_presence": taux,
        "alertes": alertes,
        "nb_critiques": sum(1 for a in alertes if a[0] == "critique"),
        "carte": {
            "vehicules": vehicules_carte,
            "colors": SITUATION_COLORS,
            "center": list(settings.FLEET_MAP_CENTER),
            "zoom": settings.FLEET_MAP_ZOOM,
        },
        "legende": [(libelles_situation.get(k, k), c) for k, c in SITUATION_COLORS.items()],
        "top_vehicule": top,
        "parc": ages_vehicules(auj),
        "carburants": ["Diesel", "Essence", "Hybride", "Électrique"],
        "recap": recap,
    }
    return render(request, "dg.html", context)
