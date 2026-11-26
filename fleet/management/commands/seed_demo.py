# -*- coding: utf-8 -*-
"""Remplit la base avec des donnees de demonstration coherentes.

Usage : python manage.py seed_demo
Les comptes utilisateurs ont tous le mot de passe : demo1234
"""
import random
from datetime import date, datetime, time, timedelta

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.utils import timezone

from fleet.stats import ajouter_annees
from fleet.utils import slug_ascii
from fleet.models import (Attribution, Chauffeur, Conge, Depense, Panne,
                          Presence, Profile, Recette, Vehicule)

random.seed(42)
AUJ = timezone.localdate()


COMMUNES_KINSHASA = ["Gombe", "Limete", "Ngaliema", "Lingwala", "Kintambo",
                     "Bandalungwa", "Kalamu", "Lemba", "Matete", "Masina"]


def tel_rdc():
    """Numéro mobile congolais fictif : +243 8x/9x xxx xxxx."""
    return (f"+243 {random.choice(['81', '82', '84', '85', '89', '97', '99'])} "
            f"{random.randint(100, 999)} {random.randint(1000, 9999)}")


def email_local(prenom, nom):
    return f"{slug_ascii(prenom)}.{slug_ascii(nom)}@fleet.local"


class Command(BaseCommand):
    help = "Charge les donnees de demonstration (comptes, flotte, recettes...)"

    def handle(self, *args, **options):
        self.vider()
        chauffeurs = self.creer_chauffeurs()
        vehicules = self.creer_vehicules()
        users = self.creer_users(chauffeurs)
        presents = self.creer_presences(chauffeurs, users)
        self.creer_recettes(chauffeurs, vehicules, users, presents)
        self.creer_pannes(chauffeurs, vehicules)
        self.creer_depenses(vehicules)
        self.creer_attributions(chauffeurs, vehicules, users)
        self.creer_conges(chauffeurs)
        self.stdout.write(self.style.SUCCESS(
            "Donnees de demo chargees. Comptes : dg / finance / rh / tech / "
            "per1..3 / chauf1..3 — mot de passe : demo1234"))

    def vider(self):
        for m in (Recette, Panne, Depense, Attribution, Presence, Conge,
                  Profile, User, Chauffeur, Vehicule):
            m.objects.all().delete()

    # ------------------------------------------------------------------
    def creer_chauffeurs(self):
        noms = [("Mbuyi", "Patrick"), ("Tshibangu", "Jean-Marie"), ("Lukusa", "Didier"),
                ("Mukendi", "Christian"), ("Kalala", "Serge"), ("Ilunga", "Patrice"),
                ("Ngoy", "Héritier"), ("Kasongo", "Fiston"), ("Mwamba", "Junior"),
                ("Nkulu", "Trésor"), ("Kayembe", "Glody"), ("Lumbu", "Cédric"),
                ("Bokele", "Dieudonné"), ("Matondo", "Blaise")]
        statuts = ["Actif"] * 11 + ["En conge"] * 2 + ["Suspendu"]
        exp_perm = [200, 300, -20, 150, 400, 90, 12, 250, 180, -5, 25, 320, 45, 120]
        objs = []
        for i, (n, p) in enumerate(noms):
            objs.append(Chauffeur(
                nom=n, prenom=p, email=email_local(p, n),
                tel=tel_rdc(),
                permis=random.choice(["B", "C", "C", "D", "E"]),
                date_naissance=date(random.randint(1964, 2002), random.randint(1, 12), random.randint(1, 28)),
                date_embauche=date(random.randint(2018, 2024), random.randint(1, 12), random.randint(1, 28)),
                statut=statuts[i],
                date_expiration_permis=AUJ + timedelta(days=exp_perm[i]),
                adresse=f"Kinshasa, {random.choice(COMMUNES_KINSHASA)}",
                personne_contact=random.choice(["Conjoint(e)", "Frère", "Sœur", "Père", "Mère"]),
                contact_urgence=tel_rdc()))
        # Deux chauffeurs proches de la retraite (65 ans en RDC), pour la pyramide des âges.
        objs[6].date_naissance = ajouter_annees(AUJ, -65) + timedelta(days=150)
        objs[9].date_naissance = ajouter_annees(AUJ, -62) - timedelta(days=40)
        Chauffeur.objects.bulk_create(objs)
        return list(Chauffeur.objects.all())

    def creer_vehicules(self):
        marques = [("Toyota", "Coaster"), ("Toyota", "Hiace"), ("Mercedes", "Sprinter"),
                   ("Isuzu", "NQR"), ("Renault", "Master"), ("Hyundai", "H350"),
                   ("Toyota", "Land Cruiser"), ("Isuzu", "Elf"), ("Mercedes", "Vito"),
                   ("Renault", "Trafic"), ("Toyota", "Dyna"), ("Hyundai", "County")]
        types = ["Bus", "Mini-bus", "Mini-bus", "Camionnette", "Fourgon", "Bus", "VIP",
                 "Camionnette", "Fourgon", "Mini-bus", "Camionnette", "Bus"]
        situations = ["En service"] * 7 + ["En panne"] * 2 + ["En maintenance"] * 2 + ["Gelee"]
        ct = [-8, 12, 15, 30, 45, 60, 90, 10, 5, 25, 120, 20]
        assu = [-15, 20, 45, 60, 80, 100, 150, 30, 10, 70, 200, 40]
        objs = []
        for i, (mq, md) in enumerate(marques):
            acquisition = min(date(random.randint(2012, 2026), random.randint(1, 12), random.randint(1, 28)),
                              AUJ - timedelta(days=30))
            objs.append(Vehicule(
                # Format RDC : 4 chiffres + 2 lettres (drapeau et « CGO » figurent sur la plaque).
                plaque=f"{random.randint(1000, 9999)}{random.choice(['AA', 'AB', 'AC', 'BA', 'BC', 'BD'])}",
                marque=mq, modele=md, numero_chassis=f"ND{random.randint(10**9, 10**10 - 1)}",
                carburant=random.choice(["Diesel", "Diesel", "Diesel", "Essence"]),
                annee_fabrication=acquisition.year - random.randint(0, 2),
                date_acquisition=acquisition,
                type_vehicule=types[i], categorie="Transport",
                kilometrage=random.randint(20000, 320000),
                situation=situations[i],
                prochain_ct=AUJ + timedelta(days=ct[i]),
                assurance_expire=AUJ + timedelta(days=assu[i]),
                # Positions simulées autour de Kinshasa (Gombe).
                latitude=round(-4.322 + random.uniform(-0.05, 0.05), 5),
                longitude=round(15.312 + random.uniform(-0.06, 0.06), 5)))
        Vehicule.objects.bulk_create(objs)
        return list(Vehicule.objects.all())

    def creer_users(self, chauffeurs):
        specs = [
            ("dg", "dg@fleet.local", "Kanku Albert", "DG", "Direction", None),
            ("finance", "finance@fleet.local", "Mbala Grâce", "TRESORIER", "Finance", None),
            ("rh", "rh@fleet.local", "Nsimba Chantal", "RH", "Ressources Humaines", None),
            ("tech", "tech@fleet.local", "Kabeya Olivier", "TECHNIQUE", "Service Technique", None),
            ("per1", "percepteur1@fleet.local", "Lokonga Pascal", "PERCEPTEUR", "Perception", None),
            ("per2", "percepteur2@fleet.local", "Mujinga Esther", "PERCEPTEUR", "Perception", None),
            ("per3", "percepteur3@fleet.local", "Bolamba Michel", "PERCEPTEUR", "Perception", None),
            ("chauf1", "chauffeur1@fleet.local", "Mbuyi Patrick", "CHAUFFEUR", "Exploitation", chauffeurs[0]),
            ("chauf2", "chauffeur2@fleet.local", "Tshibangu Jean-Marie", "CHAUFFEUR", "Exploitation", chauffeurs[1]),
            ("chauf3", "chauffeur3@fleet.local", "Lukusa Didier", "CHAUFFEUR", "Exploitation", chauffeurs[2]),
        ]
        users = []
        for username, email, nom, role, service, ch in specs:
            u = User.objects.create_user(username=username, email=email,
                                         password="demo1234", first_name=nom)
            Profile.objects.create(user=u, role=role, service=service,
                                   tel=tel_rdc(), chauffeur=ch)
            users.append(u)
        return users

    def creer_recettes(self, chauffeurs, vehicules, users, presents):
        """Une recette au plus par chauffeur et par jour, le matin (règle des 12 h).

        Les 6 premiers chauffeurs actifs roulent avec le véhicule qui leur est
        attribué (même correspondance que creer_attributions). Aujourd'hui, seuls
        2 chauffeurs ont déjà versé : les autres restent disponibles à la saisie.
        """
        ch_actifs = [c for c in chauffeurs if c.statut == "Actif"]
        v_service = [v for v in vehicules if v.situation == "En service"]
        vehicule_de = {ch_actifs[i].pk: v_service[i % len(v_service)] for i in range(6)}
        perco = [u for u in users if u.profile.role == "PERCEPTEUR"]
        maintenant = timezone.now()
        objs = []
        for j in range(364, -1, -1):
            d = AUJ - timedelta(days=j)
            dispo = presents.get(d, [])
            du_jour = dispo if j == 0 else random.sample(dispo, k=min(len(dispo), random.randint(2, 6)))
            for k, ch in enumerate(du_jour):
                fixe = 100000   # FC (≈ 25 000 FCFA au taux de ~4 FC pour 1 FCFA)
                verse = random.choice([fixe, fixe, fixe, fixe + random.choice([-8000, -4000, 4000, 8000, 12000]),
                                       int(fixe * 0.8)])
                u = random.choice(perco)
                heure = time(6 + k // 2, random.randint(0, 59))
                saisie = min(timezone.make_aware(datetime.combine(d, heure)), maintenant)
                objs.append(Recette(
                    date=d, saisie_le=saisie, num_ordre=k + 1, chauffeur=ch,
                    vehicule=vehicule_de.get(ch.pk) or random.choice(v_service), percepteur=u,
                    montant_verse=verse, montant_fixe=fixe,
                    observation="Versement partiel" if verse < fixe else "",
                    saisi_par=u.username,
                    cloturee=False if (j == 0 and random.random() < 0.5) else True))
        Recette.objects.bulk_create(objs)

    def creer_pannes(self, chauffeurs, vehicules):
        descs = [("Freins uses", "Haute", "En diagnostic"), ("Panne moteur", "Critique", "En reparation"),
                 ("Pneu creve", "Faible", "Termine"), ("Probleme electrique", "Moyenne", "Declare"),
                 ("Surchauffe radiateur", "Haute", "En reparation"), ("Embrayage HS", "Critique", "En diagnostic"),
                 ("Vitre brisee", "Faible", "Termine"), ("Climatisation HS", "Moyenne", "Declare"),
                 ("Fuite hydraulique", "Haute", "En reparation"), ("Alternateur defectueux", "Moyenne", "Termine"),
                 ("Courroie cassee", "Haute", "Termine"), ("Pompe a eau HS", "Moyenne", "Declare"),
                 ("Amortisseurs uses", "Faible", "Termine"), ("Probleme de direction", "Critique", "Declare"),
                 ("Batterie dechargee", "Faible", "Termine"), ("Fuite de carburant", "Haute", "En diagnostic")]
        ch_actifs = [c for c in chauffeurs if c.statut == "Actif"]
        Panne.objects.bulk_create([
            Panne(date_declaration=AUJ - timedelta(days=random.randint(0, 30)),
                  vehicule=random.choice(vehicules), declaree_par=random.choice(ch_actifs),
                  description=d, priorite=p, statut=s)
            for d, p, s in descs])
        # Historique : pannes résolues réparties sur les 12 derniers mois.
        Panne.objects.bulk_create([
            Panne(date_declaration=AUJ - timedelta(days=random.randint(31, 364)),
                  vehicule=random.choice(vehicules), declaree_par=random.choice(ch_actifs),
                  description=random.choice(descs)[0], priorite=random.choice(["Faible", "Moyenne", "Haute"]),
                  statut="Termine")
            for _ in range(45)])

    def creer_depenses(self, vehicules):
        # Montants en FC (anciens montants FCFA × 4 environ).
        cats = {"Carburant": (80000, 240000), "Maintenance": (60000, 600000),
                "Pièces détachées": (120000, 800000), "Assurance": (400000, 720000),
                "Péage": (8000, 40000), "Lavage": (12000, 32000), "Divers": (20000, 120000)}
        saisi = ["finance", "tech", "rh"]
        objs = []
        did = 0
        for j in range(364, -1, -1):
            d = AUJ - timedelta(days=j)
            for c, (lo, hi) in random.sample(list(cats.items()), k=random.randint(1, 2)):
                did += 1
                objs.append(Depense(
                    date=d, type_dep="Fixe" if c == "Assurance" else "Operationnelle",
                    categorie=c, montant=random.randint(lo // 1000, hi // 1000) * 1000,
                    vehicule=random.choice(vehicules),
                    justificatif=f"justificatifs/D{did:03d}.pdf",
                    saisi_par=random.choice(saisi)))
        Depense.objects.bulk_create(objs)

    def creer_attributions(self, chauffeurs, vehicules, users):
        ch_actifs = [c for c in chauffeurs if c.statut == "Actif"]
        v_service = [v for v in vehicules if v.situation == "En service"]
        rh_user = next(u for u in users if u.username == "rh")
        objs = []
        for i in range(6):
            objs.append(Attribution(
                date_debut=AUJ - timedelta(days=random.randint(0, 10)),
                chauffeur=ch_actifs[i], vehicule=v_service[i % len(v_service)],
                attribue_par=rh_user, actif=True))
        for i in range(16):
            dd = date(random.randint(2025, 2026), random.randint(1, 9), random.randint(1, 28))
            if dd > AUJ:
                dd = AUJ - timedelta(days=random.randint(20, 60))
            objs.append(Attribution(
                date_debut=dd, date_fin=min(dd + timedelta(days=random.randint(5, 45)), AUJ),
                chauffeur=random.choice(ch_actifs), vehicule=random.choice(vehicules),
                attribue_par=rh_user, actif=False))
        Attribution.objects.bulk_create(objs)

    def creer_presences(self, chauffeurs, users):
        """Pointages saisis par la RH sur un an (repos le dimanche).

        Aujourd'hui, seuls les 2 premiers chauffeurs actifs sont déjà pointés :
        les autres restent à pointer dans l'onglet RH « Pointage du jour ».
        Renvoie {date: [chauffeurs présents]} pour générer des recettes cohérentes.
        """
        rh = next(u for u in users if u.username == "rh")
        ch_actifs = [c for c in chauffeurs if c.statut == "Actif"]
        assiduite = {c.pk: random.uniform(0.85, 0.99) for c in ch_actifs}
        objs, presents = [], {}
        for j in range(364, -1, -1):
            d = AUJ - timedelta(days=j)
            if d.weekday() == 6:
                continue
            pointes = ch_actifs[:2] if j == 0 else ch_actifs
            for c in pointes:
                if j and random.random() > assiduite[c.pk]:
                    objs.append(Presence(date=d, nom=str(c), chauffeur=c, pointe_par=rh,
                                         statut="Absent", observation="Absence non justifiée"))
                    continue
                m = random.randint(20, 95) if j else random.randint(20, 40)
                arr = time(6 + m // 60, m % 60)
                dep = None if j == 0 else time(16 + random.randint(0, 2), random.randint(0, 59))
                objs.append(Presence(date=d, nom=str(c), chauffeur=c, pointe_par=rh,
                                     heure_arrivee=arr, heure_depart=dep,
                                     statut="Retard" if arr > time(7, 30) else "Present"))
                presents.setdefault(d, []).append(c)
        Presence.objects.bulk_create(objs, batch_size=500)
        return presents

    def creer_conges(self, chauffeurs):
        specs = [(chauffeurs[4], AUJ - timedelta(days=22), AUJ - timedelta(days=8), "Annuel", "Approuve"),
                 (chauffeurs[5], AUJ - timedelta(days=3), AUJ + timedelta(days=4), "Maladie", "Approuve"),
                 (chauffeurs[9], AUJ + timedelta(days=7), AUJ + timedelta(days=16), "Annuel", "En attente"),
                 (chauffeurs[12], AUJ - timedelta(days=5), AUJ - timedelta(days=4), "Exceptionnel", "Refuse"),
                 (chauffeurs[3], AUJ + timedelta(days=38), AUJ + timedelta(days=52), "Annuel", "En attente")]
        Conge.objects.bulk_create([
            Conge(chauffeur=c, date_debut=d1, date_fin=d2, type_conge=t, statut=s)
            for c, d1, d2, t, s in specs])
