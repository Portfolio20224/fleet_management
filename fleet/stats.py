# -*- coding: utf-8 -*-
"""Statistiques de pilotage : fiche individuelle chauffeur, pyramide des âges,
âge du parc. Fonctions pures (pas de requête HTTP) pour être testables."""
from collections import Counter
from datetime import date
from statistics import median

from django.conf import settings
from django.db.models import Count, F, Q, Sum
from django.db.models.functions import TruncMonth

from .models import Attribution, Chauffeur, Panne, Presence, Recette, Vehicule

MOIS_FR = ["janv.", "févr.", "mars", "avr.", "mai", "juin",
           "juil.", "août", "sept.", "oct.", "nov.", "déc."]


# ------------------------------------------------------------------ OUTILS DATES
def ajouter_annees(d, n):
    """d + n ans ; un 29 février devient 28 février les années non bissextiles."""
    try:
        return d.replace(year=d.year + n)
    except ValueError:
        return d.replace(year=d.year + n, day=28)


def age_revolu(naissance, auj):
    """Âge en années révolues (anniversaire passé ou non)."""
    return auj.year - naissance.year - ((auj.month, auj.day) < (naissance.month, naissance.day))


def anciennete_annees(debut, auj):
    """Durée écoulée en années décimales (pour l'âge d'un véhicule)."""
    return max((auj - debut).days, 0) / 365.25


def derniers_mois(auj, n=12):
    """Les n derniers mois, du plus ancien au mois courant : [date(aaaa, mm, 1), …]."""
    mois = []
    a, m = auj.year, auj.month
    for _ in range(n):
        mois.append(date(a, m, 1))
        a, m = (a, m - 1) if m > 1 else (a - 1, 12)
    return mois[::-1]


def libelle_mois(d):
    return f"{MOIS_FR[d.month - 1]} {d:%y}"


def _par_mois(qs, champ_date, mois):
    """Compte les lignes d'un queryset par mois, aligné sur la liste `mois`."""
    lignes = (qs.annotate(m=TruncMonth(champ_date)).values("m")
              .annotate(n=Count("id")).values_list("m", "n"))
    compte = {(m.year, m.month): n for m, n in lignes}
    return [compte.get((d.year, d.month), 0) for d in mois]


# ------------------------------------------------------------------ FICHE CHAUFFEUR
JOUR_TRAVAILLE = Q(statut__in=["Present", "Retard"])


def stats_chauffeur(chauffeur, auj, nb_mois=12):
    """KPI du mois courant + séries mensuelles sur `nb_mois` mois.

    Définitions (à garder alignées avec l'aide affichée dans le gabarit) :
    - jour travaillé : pointage « Présent » ou « Retard » saisi par la RH ;
    - écart de recette : recette dont le montant versé est INFÉRIEUR au montant fixe ;
    - panne déclarée : panne dont le chauffeur est le déclarant.
    """
    mois = derniers_mois(auj, nb_mois)
    debut = mois[0]
    debut_mois = mois[-1]

    presences = Presence.objects.filter(chauffeur=chauffeur)
    pannes = Panne.objects.filter(declaree_par=chauffeur)
    recettes = Recette.objects.filter(chauffeur=chauffeur)
    ecarts = recettes.filter(montant_verse__lt=F("montant_fixe"))

    p_mois = presences.filter(date__gte=debut_mois, date__lte=auj).aggregate(
        travailles=Count("id", filter=JOUR_TRAVAILLE),
        retards=Count("id", filter=Q(statut="Retard")),
        absences=Count("id", filter=Q(statut="Absent")))
    r_mois = recettes.filter(date__gte=debut_mois, date__lte=auj).aggregate(
        nb=Count("id"), verse=Sum("montant_verse"), fixe=Sum("montant_fixe"))
    e_mois = ecarts.filter(date__gte=debut_mois, date__lte=auj).aggregate(
        nb=Count("id"), fixe=Sum("montant_fixe"), verse=Sum("montant_verse"))

    return {
        "chauffeur": chauffeur,
        "mois_courant": libelle_mois(debut_mois),
        "kpi": {
            "jours_travailles": p_mois["travailles"],
            "retards": p_mois["retards"],
            "absences": p_mois["absences"],
            "pannes": pannes.filter(date_declaration__gte=debut_mois).count(),
            "ecarts": e_mois["nb"],
            "manque": (e_mois["fixe"] or 0) - (e_mois["verse"] or 0),
            "recettes": r_mois["nb"],
            "verse": r_mois["verse"] or 0,
        },
        # Sérialisé par json_script dans le gabarit.
        "series": {
            # Le dernier mois est partiel : on le signale sur l'axe.
            "mois": [libelle_mois(d) for d in mois[:-1]] + [libelle_mois(mois[-1]) + " (en cours)"],
            "jours": _par_mois(presences.filter(JOUR_TRAVAILLE, date__gte=debut), "date", mois),
            "pannes": _par_mois(pannes.filter(date_declaration__gte=debut), "date_declaration", mois),
            "ecarts": _par_mois(ecarts.filter(date__gte=debut), "date", mois),
        },
    }


# ------------------------------------------------------------------ ÂGES CHAUFFEURS
# Dernière tranche alignée sur l'âge de retraite en RDC (65 ans).
TRANCHES_AGE = [("< 25 ans", 0, 24), ("25–34", 25, 34), ("35–44", 35, 44),
                ("45–54", 45, 54), ("55–64", 55, 64), ("65 ans et +", 65, 200)]


def ages_chauffeurs(auj):
    """Pyramide des âges et départs prévisibles, pour anticiper les recrutements."""
    age_retraite = settings.FLEET_AGE_RETRAITE
    chauffeurs = list(Chauffeur.objects.all())
    avec_date = [c for c in chauffeurs if c.date_naissance]

    lignes = []
    for c in avec_date:
        age = age_revolu(c.date_naissance, auj)
        retraite = ajouter_annees(c.date_naissance, age_retraite)
        lignes.append({"obj": c, "age": age, "retraite": retraite,
                       "mois_avant_retraite": (retraite.year - auj.year) * 12
                                              + retraite.month - auj.month})
    lignes.sort(key=lambda x: -x["age"])

    ages = [x["age"] for x in lignes]
    tranches = Counter()
    for a in ages:
        for libelle, lo, hi in TRANCHES_AGE:
            if lo <= a <= hi:
                tranches[libelle] += 1
                break

    def departs(nb_mois):
        return sum(1 for x in lignes if x["mois_avant_retraite"] <= nb_mois)

    # Capacité : véhicules exploitables sans chauffeur, chauffeurs actifs sans véhicule.
    actives = Attribution.objects.filter(actif=True)
    vehicules_sans_chauffeur = (Vehicule.objects.filter(situation="En service")
                                .exclude(attributions__in=actives).distinct().count())
    chauffeurs_sans_vehicule = (Chauffeur.objects.filter(statut="Actif")
                                .exclude(attributions__in=actives).distinct().count())

    return {
        "age_retraite": age_retraite,
        "effectif": len(chauffeurs),
        # Liste de couples (un Counter dans un gabarit : `.items` serait lu comme une clé).
        "par_statut": sorted(Counter(c.get_statut_display() for c in chauffeurs).items()),
        "sans_date": len(chauffeurs) - len(avec_date),
        "age_moyen": round(sum(ages) / len(ages), 1) if ages else None,
        "age_median": median(ages) if ages else None,
        "departs_12": departs(12), "departs_24": departs(24), "departs_36": departs(36),
        "vehicules_sans_chauffeur": vehicules_sans_chauffeur,
        "chauffeurs_sans_vehicule": chauffeurs_sans_vehicule,
        "proches_retraite": [x for x in lignes if x["mois_avant_retraite"] <= 60],
        "graph": {"tranches": [t[0] for t in TRANCHES_AGE],
                  "effectifs": [tranches[t[0]] for t in TRANCHES_AGE]},
    }


# ------------------------------------------------------------------ ÂGE DU PARC
TRANCHES_VEHICULE = [("< 2 ans", 0, 2), ("2–4 ans", 2, 4), ("4–6 ans", 4, 6),
                     ("6–8 ans", 6, 8), ("8–10 ans", 8, 10), ("10 ans et +", 10, 999)]


def ages_vehicules(auj):
    """Âge du parc depuis la date d'acquisition, pour planifier les achats."""
    seuil = settings.FLEET_AGE_RENOUVELLEMENT_VEHICULE
    vehicules = list(Vehicule.objects.all())
    lignes = []
    for v in vehicules:
        if not v.date_acquisition:
            continue
        age = anciennete_annees(v.date_acquisition, auj)
        echeance = ajouter_annees(v.date_acquisition, seuil)
        lignes.append({"obj": v, "age": age, "echeance": echeance,
                       "a_renouveler": age >= seuil,
                       "sous_12_mois": not age >= seuil and (echeance - auj).days <= 365})
    lignes.sort(key=lambda x: -x["age"])

    tranches = Counter()
    for x in lignes:
        for libelle, lo, hi in TRANCHES_VEHICULE:
            if lo <= x["age"] < hi:
                tranches[libelle] += 1
                break

    ages = [x["age"] for x in lignes]
    return {
        "seuil": seuil,
        "nb": len(vehicules),
        "sans_date": len(vehicules) - len(lignes),
        "age_moyen": round(sum(ages) / len(ages), 1) if ages else None,
        "plus_ancien": lignes[0] if lignes else None,
        "a_renouveler": sum(1 for x in lignes if x["a_renouveler"]),
        "sous_12_mois": sum(1 for x in lignes if x["sous_12_mois"]),
        "lignes": lignes,
        "graph": {"tranches": [t[0] for t in TRANCHES_VEHICULE],
                  "effectifs": [tranches[t[0]] for t in TRANCHES_VEHICULE]},
    }
