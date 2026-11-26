# -*- coding: utf-8 -*-
"""Tests : filtres, contrôle d'accès, exports et principaux formulaires.

Lancer : python manage.py test fleet
"""
import io
import shutil
import tempfile
from datetime import timedelta

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import (Attribution, Chauffeur, Conge, Depense, Panne, Profile,
                     Recette, Vehicule)
from .templatetags.filters import get_item, monnaie, next_etape
from .views import _csv_safe

AUJ = timezone.localdate()

# Les fichiers envoyés pendant les tests vont dans un dossier temporaire, supprimé à la fin.
MEDIA_TESTS = tempfile.mkdtemp(prefix="fleet-tests-media-")


def tearDownModule():
    shutil.rmtree(MEDIA_TESTS, ignore_errors=True)


def png_bytes():
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (2, 2), "red").save(buf, format="PNG")
    return buf.getvalue()


class FiltresTests(TestCase):
    def test_monnaie(self):
        self.assertEqual(monnaie(100000), "100\xa0000\xa0FC")
        self.assertEqual(monnaie(-1500), "-1\xa0500\xa0FC")
        self.assertEqual(monnaie("1234.6"), "1\xa0235\xa0FC")
        self.assertEqual(monnaie(None), "—")
        self.assertEqual(monnaie("abc"), "—")

    def test_slug_ascii(self):
        from .utils import slug_ascii
        self.assertEqual(slug_ascii("Héritier"), "heritier")
        self.assertEqual(slug_ascii("Jean-Marie N'Zi"), "jean-marie-nzi")

    def test_get_item_et_next_etape_tolerent_none(self):
        self.assertEqual(get_item(None, "x"), [])
        self.assertEqual(get_item({"a": [1]}, "a"), [1])
        self.assertEqual(next_etape(None, "a"), "")
        self.assertEqual(next_etape(["a", "b"], "a"), "b")
        self.assertEqual(next_etape(["a", "b"], "b"), "")

    def test_csv_safe(self):
        self.assertEqual(_csv_safe("=SUM(A1)"), "'=SUM(A1)")
        self.assertEqual(_csv_safe("@cmd"), "'@cmd")
        self.assertEqual(_csv_safe(-2000), -2000)   # un nombre négatif reste un nombre
        self.assertEqual(_csv_safe(None), "")


@override_settings(MEDIA_ROOT=MEDIA_TESTS)
class BaseFleetTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ch = Chauffeur.objects.create(nom="Camara", prenom="Ibrahim")
        cls.ch2 = Chauffeur.objects.create(nom="Sylla", prenom="Moussa")
        cls.ve = Vehicule.objects.create(plaque="1001AA", marque="Toyota", modele="Hiace",
                                         latitude=0.0, longitude=0.0)
        cls.ve_sans_dates = Vehicule.objects.create(plaque="1002AA", marque="Isuzu", modele="Elf")
        cls.users = {}
        for role in ("DG", "TRESORIER", "RH", "TECHNIQUE", "PERCEPTEUR", "CHAUFFEUR"):
            u = User.objects.create_user(username=role.lower(), password="x")
            Profile.objects.create(user=u, role=role,
                                   chauffeur=cls.ch if role == "CHAUFFEUR" else None)
            cls.users[role] = u
        cls.sans_role = User.objects.create_user(username="norole", password="x")
        Attribution.objects.create(date_debut=AUJ, chauffeur=cls.ch, vehicule=cls.ve)
        Panne.objects.create(date_declaration=AUJ, vehicule=cls.ve, description="Freins",
                             priorite="Critique")
        Depense.objects.create(date=AUJ, categorie="=HYPERLINK(\"x\")", montant=1000)

    def login(self, role):
        self.client.force_login(self.users[role])


class AccesTests(BaseFleetTest):
    PAGES = {"percepteur": ("PERCEPTEUR", "DG"), "chauffeur": ("CHAUFFEUR", "DG"),
             "technique": ("TECHNIQUE", "DG"), "rh": ("RH", "DG"),
             "finance": ("TRESORIER", "DG"), "dg": ("DG",)}

    def test_anonyme_redirige_avec_next(self):
        r = self.client.get(reverse("fleet:rh"))
        self.assertEqual(r.status_code, 302)
        self.assertIn("next=/rh/", r["Location"])

    def test_chaque_page_rend_pour_les_roles_autorises_et_403_sinon(self):
        for page, roles in self.PAGES.items():
            for role in self.users:
                self.login(role)
                r = self.client.get(reverse(f"fleet:{page}"))
                attendu = 200 if role in roles else 403
                self.assertEqual(r.status_code, attendu, f"{page} / {role}")

    def test_home_sans_role_affiche_un_avertissement(self):
        self.client.force_login(self.sans_role)
        r = self.client.get(reverse("fleet:home"))
        self.assertContains(r, "Aucun rôle")
        self.assertNotContains(r, "Administration")

    def test_rh_vehicule_sans_dates_affiche_tiret(self):
        self.login("RH")
        r = self.client.get(reverse("fleet:rh") + "?tab=vehicules")
        self.assertNotContains(r, ">None<")

    @override_settings(SHOW_DEMO_ACCOUNTS=False)
    def test_comptes_demo_masques(self):
        r = self.client.get(reverse("login"))
        self.assertNotContains(r, "demo1234")


class PercepteurTests(BaseFleetTest):
    def post(self, **data):
        self.login("PERCEPTEUR")
        base = {"action": "recette", "chauffeur": self.ch.pk, "vehicule": self.ve.pk,
                "montant_verse": "100000", "montant_fixe": "100000"}
        base.update(data)
        return self.client.post(reverse("fleet:percepteur"), base)

    def setUp(self):
        # Deuxième chauffeur avec son propre véhicule attribué.
        Attribution.objects.create(date_debut=AUJ, chauffeur=self.ch2, vehicule=self.ve_sans_dates)

    def post_deux_chauffeurs(self):
        self.post()
        self.post(chauffeur=self.ch2.pk, vehicule=self.ve_sans_dates.pk)

    def test_numeros_ordre_successifs(self):
        self.post_deux_chauffeurs()
        self.assertEqual(sorted(Recette.objects.values_list("num_ordre", flat=True)), [1, 2])

    def test_double_recette_meme_chauffeur_refusee_sous_12h(self):
        self.post(); self.post(montant_verse="1000")
        self.assertEqual(Recette.objects.filter(chauffeur=self.ch).count(), 1)

    def test_nouvelle_recette_possible_apres_12h(self):
        self.post()
        Recette.objects.update(saisie_le=timezone.now() - timedelta(hours=12, minutes=1))
        self.post()
        self.assertEqual(Recette.objects.filter(chauffeur=self.ch).count(), 2)

    def test_vehicule_non_attribue_refuse(self):
        self.post(vehicule=self.ve_sans_dates.pk)   # attribué à ch2, pas à ch
        self.assertFalse(Recette.objects.exists())

    def test_vehicule_deduit_de_l_attribution(self):
        self.post(vehicule="")
        self.assertEqual(Recette.objects.get().vehicule, self.ve)

    def test_chauffeur_sans_attribution_refuse(self):
        sans = Chauffeur.objects.create(nom="Kone", prenom="Ali")
        self.post(chauffeur=sans.pk)
        self.assertFalse(Recette.objects.exists())

    def test_liste_filtree_par_attribution_et_chauffeur_bloque_grise(self):
        Chauffeur.objects.create(nom="SansVehicule", prenom="X")
        self.post()
        r = self.client.get(reverse("fleet:percepteur"))
        self.assertNotContains(r, "SansVehicule")
        self.assertContains(r, f'value="{self.ch.pk}" data-vehicules="{self.ve.pk}"\n                  disabled')

    def test_id_forge_404(self):
        self.assertEqual(self.post(chauffeur="99999").status_code, 404)
        self.assertEqual(Recette.objects.count(), 0)

    def test_montant_invalide(self):
        self.post(montant_verse="abc")
        self.assertEqual(Recette.objects.count(), 0)

    def test_upload_non_image_refuse(self):
        self.post(capture=SimpleUploadedFile("x.png", b"pas une image", content_type="image/png"))
        self.assertEqual(Recette.objects.count(), 0)

    @override_settings(FLEET_UPLOAD_MAX_BYTES=10)
    def test_upload_trop_gros_refuse(self):
        self.post(capture=SimpleUploadedFile("x.png", png_bytes(), content_type="image/png"))
        self.assertEqual(Recette.objects.count(), 0)

    def test_cloture_multiple_limitee_a_ses_recettes(self):
        self.post_deux_chauffeurs()
        autre = Recette.objects.create(date=AUJ, num_ordre=99, chauffeur=self.ch,
                                       vehicule=self.ve, percepteur=self.users["DG"])
        ids = list(Recette.objects.values_list("id", flat=True))
        self.client.post(reverse("fleet:percepteur"), {"action": "cloturer", "recette_ids": ids})
        self.assertEqual(Recette.objects.filter(cloturee=True).count(), 2)
        autre.refresh_from_db()
        self.assertFalse(autre.cloturee)


class ChauffeurTests(BaseFleetTest):
    def test_panne_sur_autre_vehicule_refusee(self):
        self.login("CHAUFFEUR")
        r = self.client.post(reverse("fleet:chauffeur"), {
            "action": "panne", "vehicule": self.ve_sans_dates.pk,
            "description": "x", "priorite": "Faible"})
        self.assertEqual(r.status_code, 404)

    def test_description_vide_refusee(self):
        self.login("CHAUFFEUR")
        avant = Panne.objects.count()
        self.client.post(reverse("fleet:chauffeur"), {
            "action": "panne", "vehicule": self.ve.pk, "description": "  ", "priorite": "Faible"})
        self.assertEqual(Panne.objects.count(), avant)


class TechniqueTests(BaseFleetTest):
    def test_avance_etape(self):
        self.login("TECHNIQUE")
        p = Panne.objects.get()
        self.client.post(reverse("fleet:technique"), {"panne_id": p.pk})
        p.refresh_from_db()
        self.assertEqual(p.statut, "En diagnostic")

    def test_panne_inexistante_404(self):
        self.login("TECHNIQUE")
        self.assertEqual(self.client.post(reverse("fleet:technique"),
                                          {"panne_id": "999"}).status_code, 404)


class RHTests(BaseFleetTest):
    def test_decision_arbitraire_refusee(self):
        c = Conge.objects.create(chauffeur=self.ch, date_debut=AUJ, date_fin=AUJ)
        self.login("RH")
        self.client.post(reverse("fleet:rh"), {"action": "decision", "conge_id": c.pk,
                                               "decision": "<script>"})
        c.refresh_from_db()
        self.assertEqual(c.statut, "En attente")

    def test_conge_dates_inversees_refuse(self):
        self.login("RH")
        self.client.post(reverse("fleet:rh"), {
            "action": "add_conge", "chauffeur": self.ch.pk, "type_conge": "Annuel",
            "date_debut": str(AUJ), "date_fin": str(AUJ - timedelta(days=1))})
        self.assertFalse(Conge.objects.exists())

    def test_attribution_gele_l_ancienne_et_garde_l_onglet(self):
        self.login("RH")
        r = self.client.post(reverse("fleet:rh"), {
            "action": "attribution", "chauffeur": self.ch2.pk, "vehicule": self.ve.pk,
            "tab": "attributions"})
        self.assertTrue(r["Location"].endswith("?tab=attributions"))
        ancienne = Attribution.objects.get(chauffeur=self.ch)
        self.assertTrue(ancienne.gelee)
        self.assertFalse(ancienne.actif)
        self.assertEqual(ancienne.nouveau_chauffeur, self.ch2)

    def test_attribution_chauffeur_inexistant_ne_gele_rien(self):
        self.login("RH")
        r = self.client.post(reverse("fleet:rh"), {
            "action": "attribution", "chauffeur": "999", "vehicule": self.ve.pk})
        self.assertEqual(r.status_code, 404)
        self.assertTrue(Attribution.objects.get(chauffeur=self.ch).actif)


class ExportTests(BaseFleetTest):
    def test_export_depenses_neutralise_les_formules(self):
        self.login("TRESORIER")
        r = self.client.get(reverse("fleet:finance") + "?export=depenses")
        contenu = b"".join(r.streaming_content).decode("utf-8")
        self.assertTrue(contenu.startswith("﻿"))
        self.assertIn("'=HYPERLINK", contenu)

    def test_rapport_dg(self):
        self.login("DG")
        r = self.client.get(reverse("fleet:dg") + "?mois=2026-13&export=rapport")
        self.assertEqual(r.status_code, 200)
        self.assertIn("attachment", r["Content-Disposition"])


# ====================================================================== AJOUTS 26/11
from datetime import date as _date  # noqa: E402

from .models import Presence  # noqa: E402
from .stats import (age_revolu, ages_chauffeurs, ages_vehicules,  # noqa: E402
                    ajouter_annees, stats_chauffeur)


class OutilsStatsTests(TestCase):
    def test_age_et_annees(self):
        self.assertEqual(age_revolu(_date(1990, 6, 15), _date(2026, 6, 14)), 35)
        self.assertEqual(age_revolu(_date(1990, 6, 15), _date(2026, 6, 15)), 36)
        self.assertEqual(ajouter_annees(_date(2024, 2, 29), 1), _date(2025, 2, 28))


class PointageRHTests(BaseFleetTest):
    def pointer(self, quoi, heure="", chauffeur=None, role="RH"):
        self.login(role)
        return self.client.post(reverse("fleet:rh"), {
            "action": "pointage", "tab": "pointage", "quoi": quoi, "heure": heure,
            "chauffeur": (chauffeur or self.ch).pk})

    def test_arrivee_retard_puis_depart(self):
        r = self.pointer("arrivee", "07:45")
        self.assertTrue(r["Location"].endswith("?tab=pointage"))
        p = Presence.objects.get(chauffeur=self.ch, date=AUJ)
        self.assertEqual(p.statut, "Retard")
        self.assertEqual(p.pointe_par, self.users["RH"])
        self.pointer("depart", "07:40")                  # avant l'arrivée : refusé
        p.refresh_from_db()
        self.assertIsNone(p.heure_depart)
        self.pointer("depart", "07:50")
        p.refresh_from_db()
        self.assertEqual(p.heure_depart.strftime("%H:%M"), "07:50")

    def test_heure_future_refusee(self):
        self.pointer("arrivee", "23:59")
        if timezone.localtime().strftime("%H:%M") < "23:59":
            self.assertFalse(Presence.objects.exists())

    def test_absent_puis_arrivee_corrige(self):
        self.pointer("absent")
        self.assertEqual(Presence.objects.get().statut, "Absent")
        self.pointer("arrivee", "06:00")
        self.assertEqual(Presence.objects.get().statut, "Present")

    def test_conge_approuve_bloque_le_pointage(self):
        Conge.objects.create(chauffeur=self.ch, date_debut=AUJ, date_fin=AUJ, statut="Approuve")
        self.pointer("arrivee", "06:00")
        self.assertFalse(Presence.objects.exists())

    def test_chauffeur_ne_peut_plus_se_pointer(self):
        self.login("CHAUFFEUR")
        self.client.post(reverse("fleet:chauffeur"), {"action": "arrivee"})
        self.assertFalse(Presence.objects.exists())
        self.assertEqual(self.pointer("arrivee", "06:00", role="CHAUFFEUR").status_code, 403)


class AjoutChauffeurTests(BaseFleetTest):
    def post(self, **data):
        self.login("RH")
        base = {"action": "add_chauffeur", "nom": "Diallo", "prenom": "Awa", "permis": "D",
                "date_naissance": "1990-01-01", "date_expiration_permis": "2030-01-01"}
        base.update(data)
        return self.client.post(reverse("fleet:rh"), base)

    def test_dates_enregistrees(self):
        self.post()
        c = Chauffeur.objects.get(nom="Diallo")
        self.assertEqual(c.date_expiration_permis, _date(2030, 1, 1))
        self.assertEqual(c.date_naissance, _date(1990, 1, 1))

    def test_expiration_obligatoire_et_majorite(self):
        self.post(date_expiration_permis="")
        self.post(date_naissance=str(AUJ - timedelta(days=365 * 10)))
        self.assertFalse(Chauffeur.objects.filter(nom="Diallo").exists())


class StatsChauffeurTests(BaseFleetTest):
    def test_definitions(self):
        Presence.objects.create(chauffeur=self.ch, date=AUJ, nom="x", statut="Retard")
        Presence.objects.create(chauffeur=self.ch, date=AUJ - timedelta(days=40), nom="x", statut="Absent")
        Recette.objects.create(date=AUJ, num_ordre=1, chauffeur=self.ch, vehicule=self.ve,
                               percepteur=self.users["DG"], montant_verse=80000, montant_fixe=100000)
        Recette.objects.create(date=AUJ, num_ordre=2, chauffeur=self.ch, vehicule=self.ve,
                               percepteur=self.users["DG"], montant_verse=104000, montant_fixe=100000)
        Panne.objects.create(date_declaration=AUJ, vehicule=self.ve, declaree_par=self.ch, description="x")
        s = stats_chauffeur(self.ch, AUJ)
        self.assertEqual(s["kpi"]["jours_travailles"], 1)
        self.assertEqual(s["kpi"]["ecarts"], 1)          # seul le versement inférieur compte
        self.assertEqual(s["kpi"]["manque"], 20000)
        self.assertEqual(s["kpi"]["pannes"], 1)
        self.assertEqual(len(s["series"]["mois"]), 12)
        self.assertEqual(s["series"]["jours"][-1], 1)

    def test_rh_voit_la_fiche_du_chauffeur_choisi(self):
        self.login("RH")
        r = self.client.get(reverse("fleet:rh") + f"?tab=stats&chauffeur={self.ch.pk}")
        self.assertContains(r, 'id="stats-chauffeur-data"')

    def test_chauffeur_voit_ses_stats(self):
        self.login("CHAUFFEUR")
        r = self.client.get(reverse("fleet:chauffeur"))
        self.assertContains(r, "Mes statistiques")


class AgesTests(BaseFleetTest):
    def test_pyramide_et_departs(self):
        Chauffeur.objects.filter(pk=self.ch.pk).update(date_naissance=ajouter_annees(AUJ, -64))
        a = ages_chauffeurs(AUJ)
        self.assertEqual(a["sans_date"], 1)
        self.assertEqual(a["departs_12"], 1)
        self.assertEqual(sum(a["graph"]["effectifs"]), 1)
        self.assertEqual(a["vehicules_sans_chauffeur"], 1)   # 1002AA en service, non attribué

    def test_parc(self):
        Vehicule.objects.filter(pk=self.ve.pk).update(date_acquisition=ajouter_annees(AUJ, -9))
        Vehicule.objects.filter(pk=self.ve_sans_dates.pk).update(
            date_acquisition=ajouter_annees(AUJ, -7) - timedelta(days=30))
        p = ages_vehicules(AUJ)
        self.assertEqual(p["a_renouveler"], 1)
        self.assertEqual(p["sous_12_mois"], 1)
        self.assertEqual(p["plus_ancien"]["obj"], self.ve)


class AjoutsFormulairesTests(BaseFleetTest):
    def test_ajout_vehicule_et_plaque_unique(self):
        self.login("DG")
        data = {"action": "add_vehicule", "plaque": "9876ab", "marque": "Toyota", "modele": "Hiace",
                "date_acquisition": "2024-03-01", "annee_fabrication": "2023", "kilometrage": "100"}
        self.client.post(reverse("fleet:dg"), data)
        self.assertTrue(Vehicule.objects.filter(plaque="9876AB").exists())
        self.client.post(reverse("fleet:dg"), dict(data, plaque="9876AB"))
        self.assertEqual(Vehicule.objects.filter(plaque="9876AB").count(), 1)

    def test_ajout_vehicule_reserve_a_la_dg(self):
        self.login("TRESORIER")
        r = self.client.post(reverse("fleet:dg"), {"action": "add_vehicule", "plaque": "X"})
        self.assertEqual(r.status_code, 403)

    def test_ajout_depense(self):
        self.login("TRESORIER")
        url = reverse("fleet:finance")
        base = {"action": "add_depense", "date": str(AUJ), "categorie": "Carburant",
                "montant": "35000", "commentaire": "Plein"}
        self.client.post(url, base)
        d = Depense.objects.get(categorie="Carburant")
        self.assertEqual((d.montant, d.commentaire, d.type_dep), (35000, "Plein", "Operationnelle"))
        self.client.post(url, dict(base, categorie="carburant", montant="1000"))
        self.assertEqual(Depense.objects.filter(categorie="Carburant").count(), 2)   # orthographe reprise
        self.client.post(url, dict(base, date=str(AUJ + timedelta(days=1))))
        self.client.post(url, dict(base, montant="-5"))
        self.client.post(url, dict(base, montant="0"))
        self.assertEqual(Depense.objects.filter(categorie="Carburant").count(), 2)


class MonnaieTests(BaseFleetTest):
    def test_pages_en_francs_congolais(self):
        self.login("DG")
        for page in ("finance", "dg", "percepteur"):
            r = self.client.get(reverse(f"fleet:{page}"))
            self.assertNotContains(r, "FCFA")
        self.assertContains(self.client.get(reverse("fleet:finance")), "Montant (FC)")

    def test_commande_conversion(self):
        from django.core.management import call_command
        Depense.objects.update(montant=1000)
        call_command("convertir_monnaie", taux="4,05", stdout=io.StringIO())       # aperçu
        self.assertEqual(Depense.objects.get().montant, 1000)
        call_command("convertir_monnaie", taux="4,05", appliquer=True, stdout=io.StringIO())
        self.assertEqual(Depense.objects.get().montant, 4050)


# ====================================================================== COMPTES ET MOTS DE PASSE
class MotDePasseTests(BaseFleetTest):
    def test_changer_son_mot_de_passe(self):
        u = self.users["PERCEPTEUR"]
        u.set_password("ancien-mdp-1"); u.save()
        self.client.force_login(u)
        r = self.client.post(reverse("fleet:mot_de_passe"), {
            "old_password": "ancien-mdp-1", "new_password1": "Kinshasa-2026!", "new_password2": "Kinshasa-2026!"})
        self.assertRedirects(r, reverse("fleet:home"))
        u.refresh_from_db()
        self.assertTrue(u.check_password("Kinshasa-2026!"))
        # la session reste ouverte après le changement
        self.assertEqual(self.client.get(reverse("fleet:percepteur")).status_code, 200)

    def test_mot_de_passe_trop_simple_refuse(self):
        u = self.users["PERCEPTEUR"]
        u.set_password("ancien-mdp-1"); u.save()
        self.client.force_login(u)
        r = self.client.post(reverse("fleet:mot_de_passe"), {
            "old_password": "ancien-mdp-1", "new_password1": "12345678", "new_password2": "12345678"})
        self.assertEqual(r.status_code, 200)
        u.refresh_from_db()
        self.assertTrue(u.check_password("ancien-mdp-1"))

    def test_mot_de_passe_provisoire_oblige_a_changer(self):
        u = self.users["PERCEPTEUR"]
        u.set_password("Prov-1234-abcd"); u.save()
        Profile.objects.filter(user=u).update(doit_changer_mdp=True)
        self.client.force_login(u)
        self.assertRedirects(self.client.get(reverse("fleet:percepteur")), reverse("fleet:mot_de_passe"))
        self.client.post(reverse("fleet:mot_de_passe"), {
            "old_password": "Prov-1234-abcd", "new_password1": "Lubumbashi#77", "new_password2": "Lubumbashi#77"})
        self.assertFalse(Profile.objects.get(user=u).doit_changer_mdp)
        self.assertEqual(self.client.get(reverse("fleet:percepteur")).status_code, 200)


class ComptesRHTests(BaseFleetTest):
    def post(self, qui="RH", **data):
        self.login(qui)
        data.setdefault("tab", "comptes")
        return self.client.post(reverse("fleet:rh"), data)

    def test_creer_compte_chauffeur_relie_a_sa_fiche(self):
        r = self.post(action="creer_compte", role="CHAUFFEUR", chauffeur=self.ch2.pk)
        self.assertTrue(r["Location"].endswith("?tab=comptes"))
        p = Profile.objects.get(chauffeur=self.ch2)
        self.assertEqual(p.user.username, "moussa.sylla")
        self.assertTrue(p.doit_changer_mdp)
        page = self.client.get(r["Location"]).content.decode()
        self.assertIn("moussa.sylla", page)
        mdp = page.split('user-select-all">')[1].split("<")[0]
        self.assertTrue(p.user.check_password(mdp))
        # affiché une seule fois
        self.assertNotIn(mdp, self.client.get(r["Location"]).content.decode())

    def test_fiche_deja_reliee_refusee(self):
        self.post(action="creer_compte", role="CHAUFFEUR", chauffeur=self.ch.pk)   # ch a déjà un compte
        self.assertEqual(Profile.objects.filter(chauffeur=self.ch).count(), 1)

    def test_creer_compte_personnel_et_identifiant_unique(self):
        self.post(action="creer_compte", role="PERCEPTEUR", nom="Mujinga", prenom="Esther")
        self.post(action="creer_compte", role="PERCEPTEUR", nom="Mujinga", prenom="Esther")
        self.assertTrue(User.objects.filter(username="esther.mujinga").exists())
        self.assertTrue(User.objects.filter(username="esther.mujinga2").exists())

    def test_rh_ne_cree_pas_de_compte_dg(self):
        self.post(action="creer_compte", role="DG", nom="X", prenom="Y")
        self.assertFalse(User.objects.filter(username="y.x").exists())

    def test_dg_peut_creer_un_compte_dg(self):
        self.login("DG")
        self.client.post(reverse("fleet:rh"), {"action": "creer_compte", "role": "DG",
                                                "nom": "Kanku", "prenom": "Albert", "tab": "comptes"})
        self.assertEqual(User.objects.get(username="albert.kanku").role_name, "DG")

    def test_reinitialiser_et_desactiver(self):
        cible = self.users["PERCEPTEUR"]
        self.post(action="reinit_mdp", user_id=cible.pk)
        self.assertTrue(Profile.objects.get(user=cible).doit_changer_mdp)
        self.post(action="desactiver", user_id=cible.pk)
        cible.refresh_from_db()
        self.assertFalse(cible.is_active)
        self.post(action="activer", user_id=cible.pk)
        cible.refresh_from_db()
        self.assertTrue(cible.is_active)

    def test_garde_fous(self):
        dg, rh = self.users["DG"], self.users["RH"]
        admin_user = User.objects.create_superuser("admin", "a@x.cd", "x")
        for cible in (dg, rh, admin_user):            # compte DG, soi-même, administrateur
            self.post(action="desactiver", user_id=cible.pk)
            cible.refresh_from_db()
            self.assertTrue(cible.is_active, cible.username)

    def test_chauffeur_ne_peut_pas_creer_de_compte(self):
        self.login("CHAUFFEUR")
        r = self.client.post(reverse("fleet:rh"), {"action": "creer_compte", "role": "RH",
                                                    "nom": "A", "prenom": "B"})
        self.assertEqual(r.status_code, 403)


# ====================================================================== COMPLÉMENTS (couverture)
from .views import _alertes, to_date  # noqa: E402


class AlertesDGTests(BaseFleetTest):
    """Les alertes de la page DG : seuils, contenu et ordre (critiques d'abord)."""

    def alertes(self):
        return _alertes(AUJ)

    def textes(self, niveau=None):
        return [t for n, t in self.alertes() if niveau in (None, n)]

    def test_assurance_et_ct(self):
        Vehicule.objects.filter(pk=self.ve.pk).update(
            assurance_expire=AUJ - timedelta(days=3), prochain_ct=AUJ + timedelta(days=10))
        Vehicule.objects.filter(pk=self.ve_sans_dates.pk).update(
            assurance_expire=AUJ + timedelta(days=15), prochain_ct=AUJ - timedelta(days=1))
        critiques = " | ".join(self.textes("critique"))
        warnings = " | ".join(self.textes("warning"))
        self.assertIn("Assurance EXPIRÉE depuis 3 j — 1001AA", critiques)
        self.assertIn("Contrôle technique DÉPASSÉ de 1 j — 1002AA", critiques)
        self.assertIn("CT sous 15 jours (10 j restants) — 1001AA", warnings)
        self.assertIn("Assurance sous 15 jours (15 j restants) — 1002AA", warnings)

    def test_au_dela_du_seuil_pas_d_alerte(self):
        Vehicule.objects.update(assurance_expire=AUJ + timedelta(days=16),
                                prochain_ct=AUJ + timedelta(days=16))
        Panne.objects.update(statut="Termine")
        self.assertEqual(self.alertes(), [])

    def test_permis(self):
        Chauffeur.objects.filter(pk=self.ch.pk).update(date_expiration_permis=AUJ - timedelta(days=1))
        Chauffeur.objects.filter(pk=self.ch2.pk).update(date_expiration_permis=AUJ + timedelta(days=30))
        self.assertTrue(any("Permis EXPIRÉ — Ibrahim Camara" in t for t in self.textes("critique")))
        self.assertTrue(any("Permis expire dans 30 j — Moussa Sylla" in t for t in self.textes("warning")))

    def test_panne_critique_seulement_si_ouverte(self):
        self.assertTrue(any("Panne CRITIQUE ouverte — Freins" in t for t in self.textes("critique")))
        Panne.objects.update(statut="Termine")
        self.assertFalse(any("Panne CRITIQUE" in t for t in self.textes()))

    def test_critiques_en_premier(self):
        Vehicule.objects.filter(pk=self.ve.pk).update(assurance_expire=AUJ + timedelta(days=5))
        Vehicule.objects.filter(pk=self.ve_sans_dates.pk).update(prochain_ct=AUJ - timedelta(days=2))
        niveaux = [n for n, _ in self.alertes()]
        self.assertEqual(niveaux, sorted(niveaux, key=lambda n: n != "critique"))
        self.assertEqual(niveaux[0], "critique")

    def test_page_dg_affiche_le_compte(self):
        self.login("DG")
        r = self.client.get(reverse("fleet:dg"))
        self.assertContains(r, "dont 1 critiques")
        self.assertContains(r, "Panne CRITIQUE ouverte")


class PanneChauffeurTests(BaseFleetTest):
    def declarer(self, role="CHAUFFEUR", **data):
        self.login(role)
        base = {"action": "panne", "vehicule": self.ve.pk, "description": "Embrayage qui patine",
                "priorite": "Haute"}
        base.update(data)
        return self.client.post(reverse("fleet:chauffeur"), base)

    def test_declaration_reussie_avec_photo(self):
        photo = SimpleUploadedFile("panne.png", png_bytes(), content_type="image/png")
        r = self.declarer(photo=photo)
        self.assertRedirects(r, reverse("fleet:chauffeur"))
        p = Panne.objects.get(description="Embrayage qui patine")
        self.assertEqual((p.vehicule, p.declaree_par, p.priorite, p.statut), (self.ve, self.ch, "Haute", "Declare"))
        self.assertTrue(p.photo.name.startswith("pannes/"))

    def test_priorite_inconnue_devient_moyenne(self):
        self.declarer(priorite="Urgentissime")
        self.assertEqual(Panne.objects.get(description="Embrayage qui patine").priorite, "Moyenne")

    def test_photo_qui_n_est_pas_une_image(self):
        self.declarer(photo=SimpleUploadedFile("x.png", b"%PDF-1.4", content_type="image/png"))
        self.assertFalse(Panne.objects.filter(description="Embrayage qui patine").exists())

    def test_la_dg_peut_declarer_sur_tout_vehicule(self):
        self.declarer(role="DG", vehicule=self.ve_sans_dates.pk)
        p = Panne.objects.get(description="Embrayage qui patine")
        self.assertEqual(p.vehicule, self.ve_sans_dates)
        self.assertIsNone(p.declaree_par)

    def test_chauffeur_sans_vehicule_ne_peut_rien_declarer(self):
        Attribution.objects.update(actif=False)
        self.assertEqual(self.declarer().status_code, 404)
        self.login("CHAUFFEUR")
        self.assertContains(self.client.get(reverse("fleet:chauffeur")),
                            "dès qu'un véhicule vous sera attribué")


class TechniqueEtapesTests(BaseFleetTest):
    def test_parcours_complet_puis_blocage_a_la_fin(self):
        self.login("TECHNIQUE")
        p = Panne.objects.get()
        etapes = []
        for _ in range(5):                       # une avance de plus que nécessaire
            self.client.post(reverse("fleet:technique"), {"panne_id": p.pk})
            p.refresh_from_db()
            etapes.append(p.statut)
        self.assertEqual(etapes, ["En diagnostic", "En reparation", "Termine", "Termine", "Termine"])

    def test_kanban_affiche_les_libelles(self):
        self.login("TECHNIQUE")
        r = self.client.get(reverse("fleet:technique"))
        for libelle in ("Déclarée", "En diagnostic", "En réparation", "Terminée"):
            self.assertContains(r, libelle)


class CongesTests(BaseFleetTest):
    def post(self, **data):
        self.login("RH")
        return self.client.post(reverse("fleet:rh"), dict(data, tab="conges"))

    def test_demande_puis_approbation(self):
        self.post(action="add_conge", chauffeur=self.ch.pk, type_conge="Maladie",
                  date_debut=str(AUJ), date_fin=str(AUJ + timedelta(days=3)))
        c = Conge.objects.get()
        self.assertEqual((c.statut, c.type_conge), ("En attente", "Maladie"))
        self.post(action="decision", conge_id=c.pk, decision="Approuve")
        c.refresh_from_db()
        self.assertEqual(c.statut, "Approuve")

    def test_decision_deja_prise_non_modifiable(self):
        c = Conge.objects.create(chauffeur=self.ch, date_debut=AUJ, date_fin=AUJ, statut="Refuse")
        r = self.post(action="decision", conge_id=c.pk, decision="Approuve")
        self.assertEqual(r.status_code, 404)
        c.refresh_from_db()
        self.assertEqual(c.statut, "Refuse")

    def test_type_inconnu_et_date_impossible(self):
        self.post(action="add_conge", chauffeur=self.ch.pk, type_conge="Vacances",
                  date_debut=str(AUJ), date_fin=str(AUJ))
        self.post(action="add_conge", chauffeur=self.ch.pk, type_conge="Annuel",
                  date_debut="2026-02-30", date_fin=str(AUJ))
        self.assertFalse(Conge.objects.exists())


class PointageCasLimitesTests(BaseFleetTest):
    def pointer(self, quoi, heure=""):
        self.login("RH")
        self.client.post(reverse("fleet:rh"), {"action": "pointage", "tab": "pointage",
                                                "quoi": quoi, "heure": heure, "chauffeur": self.ch.pk})
        return Presence.objects.filter(chauffeur=self.ch, date=AUJ).first()

    def test_double_arrivee_garde_la_premiere(self):
        self.pointer("arrivee", "06:10")
        p = self.pointer("arrivee", "06:20")
        self.assertEqual(p.heure_arrivee.strftime("%H:%M"), "06:10")

    def test_double_depart_garde_le_premier(self):
        self.pointer("arrivee", "00:01")
        self.pointer("depart", "00:02")
        p = self.pointer("depart", "00:03")
        if timezone.localtime().strftime("%H:%M") >= "00:03":
            self.assertEqual(p.heure_depart.strftime("%H:%M"), "00:02")

    def test_depart_sans_arrivee_refuse(self):
        self.assertIsNone(self.pointer("depart", "00:00"))

    def test_absent_apres_arrivee_refuse(self):
        self.pointer("arrivee", "00:00")
        self.assertEqual(self.pointer("absent").statut, "Present")

    def test_heure_et_type_invalides(self):
        self.assertIsNone(self.pointer("arrivee", "25:99"))
        self.assertIsNone(self.pointer("sieste", "00:00"))

    def test_chauffeur_suspendu_non_pointable(self):
        Chauffeur.objects.filter(pk=self.ch.pk).update(statut="Suspendu")
        self.login("RH")
        r = self.client.post(reverse("fleet:rh"), {"action": "pointage", "quoi": "arrivee",
                                                    "chauffeur": self.ch.pk})
        self.assertEqual(r.status_code, 404)


class ValidationsFormulairesTests(BaseFleetTest):
    def test_to_date(self):
        self.assertEqual(to_date("2026-11-26"), _date(2026, 11, 26))
        for invalide in ("", None, "2026-02-30", "26/11/2026", "demain"):
            self.assertIsNone(to_date(invalide), invalide)

    def test_ajout_chauffeur_cas_refuses(self):
        self.login("RH")
        base = {"action": "add_chauffeur", "nom": "Diallo", "prenom": "Awa", "permis": "B",
                "date_expiration_permis": "2030-01-01"}
        for invalide in ({"nom": ""}, {"prenom": "  "}, {"permis": "Z"}):
            self.client.post(reverse("fleet:rh"), dict(base, **invalide))
        self.assertFalse(Chauffeur.objects.filter(nom="Diallo").exists())

    def test_ajout_chauffeur_permis_deja_expire_accepte_avec_avertissement(self):
        self.login("RH")
        r = self.client.post(reverse("fleet:rh"), {
            "action": "add_chauffeur", "nom": "Diallo", "prenom": "Awa", "permis": "B",
            "date_expiration_permis": str(AUJ - timedelta(days=1))}, follow=True)
        self.assertTrue(Chauffeur.objects.filter(nom="Diallo").exists())
        self.assertContains(r, "son permis a expiré")

    def test_ajout_vehicule_cas_refuses(self):
        self.login("DG")
        base = {"action": "add_vehicule", "plaque": "5555AB", "marque": "Toyota", "modele": "Hiace",
                "date_acquisition": "2024-03-01"}
        for invalide in ({"marque": ""}, {"date_acquisition": ""},
                         {"date_acquisition": str(AUJ + timedelta(days=1))},
                         {"annee_fabrication": "2026", "date_acquisition": "2020-01-01"},
                         {"annee_fabrication": "1950"}, {"kilometrage": "-5"}, {"kilometrage": "beaucoup"}):
            self.client.post(reverse("fleet:dg"), dict(base, **invalide))
        self.assertFalse(Vehicule.objects.filter(plaque="5555AB").exists())

    def test_ajout_depense_cas_refuses(self):
        self.login("TRESORIER")
        base = {"action": "add_depense", "date": str(AUJ), "categorie": "Lavage", "montant": "12000"}
        for invalide in ({"categorie": "   "}, {"type_dep": "Imaginaire"}, {"date": ""}, {"montant": "douze"}):
            self.client.post(reverse("fleet:finance"), dict(base, **invalide))
        self.assertFalse(Depense.objects.filter(categorie="Lavage").exists())

    def test_compte_identifiant_personnalise(self):
        self.login("RH")
        url = reverse("fleet:rh")
        base = {"action": "creer_compte", "role": "TECHNIQUE", "nom": "Kabeya", "prenom": "Olivier"}
        self.client.post(url, dict(base, identifiant="o kabeya!"))          # caractères interdits
        self.client.post(url, dict(base, identifiant="RH"))                 # déjà pris (casse ignorée)
        self.client.post(url, dict(base, nom=""))                           # nom manquant
        self.assertFalse(User.objects.filter(first_name__startswith="Kabeya").exists())
        self.client.post(url, dict(base, identifiant="Olivier.K"))
        self.assertEqual(User.objects.get(first_name="Kabeya Olivier").username, "olivier.k")


class PercepteurComplementsTests(BaseFleetTest):
    def test_image_valide_acceptee_et_visible(self):
        self.login("PERCEPTEUR")
        capture = SimpleUploadedFile("recu.png", png_bytes(), content_type="image/png")
        self.client.post(reverse("fleet:percepteur"), {
            "action": "recette", "chauffeur": self.ch.pk, "vehicule": self.ve.pk,
            "montant_verse": "100000", "montant_fixe": "100000", "capture": capture})
        r = Recette.objects.get()
        self.assertTrue(r.capture.name.startswith("captures/"))
        self.assertContains(self.client.get(reverse("fleet:percepteur")), r.capture.url)

    def test_cloture_sans_selection(self):
        self.login("PERCEPTEUR")
        r = self.client.post(reverse("fleet:percepteur"), {"action": "cloturer"}, follow=True)
        self.assertContains(r, "Aucune recette sélectionnée")

    def test_export_recettes_libelles_lisibles(self):
        Recette.objects.create(date=AUJ, num_ordre=1, chauffeur=self.ch, vehicule=self.ve,
                               percepteur=self.users["PERCEPTEUR"], montant_verse=90000, montant_fixe=100000)
        self.login("TRESORIER")
        r = self.client.get(reverse("fleet:finance") + "?export=recettes")
        lignes = b"".join(r.streaming_content).decode("utf-8-sig").splitlines()
        self.assertTrue(lignes[0].startswith("id;date;saisie_le;num_ordre;chauffeur;vehicule"))
        self.assertIn("Camara Ibrahim", lignes[1])
        self.assertIn("1001AA (Toyota Hiace)", lignes[1])
        self.assertIn(";90000;100000;", lignes[1])


class RoleRequiredMixinTests(TestCase):
    def test_vue_classe(self):
        from django.contrib.auth.models import AnonymousUser
        from django.core.exceptions import PermissionDenied
        from django.http import HttpResponse
        from django.test import RequestFactory
        from django.views import View

        from .decorators import RoleRequiredMixin

        class VueDG(RoleRequiredMixin, View):
            roles = ("DG",)

            def get(self, request):
                return HttpResponse("ok")

        rf = RequestFactory()
        anonyme = rf.get("/secret/"); anonyme.user = AnonymousUser()
        r = VueDG.as_view()(anonyme)
        self.assertEqual(r.status_code, 302)
        self.assertIn("next=/secret/", r["Location"])

        u = User.objects.create_user("x"); Profile.objects.create(user=u, role="RH")
        req = rf.get("/secret/"); req.user = u
        with self.assertRaises(PermissionDenied):
            VueDG.as_view()(req)
        Profile.objects.filter(user=u).update(role="DG")
        req.user = User.objects.get(pk=u.pk)
        self.assertEqual(VueDG.as_view()(req).status_code, 200)


class AdminTests(BaseFleetTest):
    def setUp(self):
        self.admin = User.objects.create_superuser("admin", "a@x.cd", "x")
        self.client.force_login(self.admin)

    def test_toutes_les_pages_admin_s_ouvrent(self):
        from django.contrib import admin as dj_admin
        for model in dj_admin.site._registry:
            info = (model._meta.app_label, model._meta.model_name)
            for vue, args in (("changelist", []), ("add", [])):
                url = reverse(f"admin:{info[0]}_{info[1]}_{vue}", args=args)
                self.assertEqual(self.client.get(url).status_code, 200, url)
            obj = model.objects.first()
            if obj:
                url = reverse(f"admin:{info[0]}_{info[1]}_change", args=[obj.pk])
                self.assertEqual(self.client.get(url).status_code, 200, url)
        # recherche (search_fields valides)
        self.assertEqual(self.client.get(reverse("admin:fleet_recette_changelist") + "?q=Camara").status_code, 200)

    def test_attribution_desactivee_recoit_une_date_de_fin(self):
        from django.contrib import admin as dj_admin
        a = Attribution.objects.get(chauffeur=self.ch)
        a.actif = False
        ma = dj_admin.site._registry[Attribution]
        req = type("R", (), {"user": self.admin})()
        ma.save_model(req, a, None, True)
        a.refresh_from_db()
        self.assertEqual(a.date_fin, AUJ)
        a.actif = True
        ma.save_model(req, a, None, True)
        a.refresh_from_db()
        self.assertIsNone(a.date_fin)

    def test_saisi_par_renseigne_automatiquement(self):
        from django.contrib import admin as dj_admin
        d = Depense(date=AUJ, categorie="Divers", montant=5000)
        req = type("R", (), {"user": self.admin})()
        dj_admin.site._registry[Depense].save_model(req, d, None, False)
        self.assertEqual(Depense.objects.get(categorie="Divers").saisi_par, "admin")


class SeedDemoTests(TestCase):
    """La commande de démonstration produit des données cohérentes avec les règles métier."""

    @classmethod
    def setUpTestData(cls):
        from django.core.management import call_command
        call_command("seed_demo", stdout=io.StringIO())

    def test_comptes_de_demo(self):
        for ident in ("dg", "finance", "rh", "tech", "per1", "chauf1"):
            u = User.objects.get(username=ident)
            self.assertTrue(u.check_password("demo1234"), ident)
            self.assertTrue(u.role_name, ident)
        self.assertEqual(User.objects.get(username="chauf1").profile.chauffeur.nom, "Mbuyi")

    def test_une_recette_par_chauffeur_et_par_jour_et_chauffeur_present(self):
        from django.db.models import Count
        doublons = (Recette.objects.values("chauffeur", "date").annotate(n=Count("id")).filter(n__gt=1))
        self.assertFalse(doublons.exists())
        presents = set(Presence.objects.filter(statut__in=["Present", "Retard"])
                       .values_list("chauffeur_id", "date"))
        self.assertTrue(all(k in presents for k in Recette.objects.values_list("chauffeur_id", "date")))

    def test_montants_en_francs_congolais_et_plaques_rdc(self):
        import re
        self.assertEqual(set(Recette.objects.values_list("montant_fixe", flat=True)), {100000})
        self.assertTrue(all(re.fullmatch(r"\d{4}[A-Z]{2}", p)
                            for p in Vehicule.objects.values_list("plaque", flat=True)))

    def test_une_attribution_active_par_vehicule(self):
        from django.db.models import Count
        self.assertFalse(Attribution.objects.filter(actif=True).values("vehicule")
                         .annotate(n=Count("id")).filter(n__gt=1).exists())


# ====================================================================== DÉPLOIEMENT
import os  # noqa: E402
from unittest import mock  # noqa: E402

from django.core.management import CommandError, call_command  # noqa: E402


class CreerAdminTests(TestCase):
    ENV = {"DJANGO_SUPERUSER_USERNAME": "admin", "DJANGO_SUPERUSER_PASSWORD": "Kinshasa-Admin-2026",
           "DJANGO_SUPERUSER_EMAIL": "admin@fleet.cd"}

    def lancer(self, env):
        with mock.patch.dict(os.environ, env, clear=False):
            out = io.StringIO()
            call_command("creer_admin", stdout=out)
            return out.getvalue()

    def test_sans_variable_ne_fait_rien(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            call_command("creer_admin", stdout=io.StringIO())
        self.assertFalse(User.objects.exists())

    def test_creation_puis_inchange(self):
        self.lancer(self.ENV)
        u = User.objects.get(username="admin")
        self.assertTrue(u.is_superuser and u.check_password("Kinshasa-Admin-2026"))
        self.assertEqual(u.role_name, "DG")
        # second démarrage avec un autre mot de passe : le compte n'est pas modifié
        out = self.lancer(dict(self.ENV, DJANGO_SUPERUSER_PASSWORD="Autre-Mot-De-Passe-99"))
        self.assertIn("existe déjà", out)
        u.refresh_from_db()
        self.assertTrue(u.check_password("Kinshasa-Admin-2026"))

    def test_mot_de_passe_faible_ou_absent_refuse(self):
        for mdp in ("12345678", "admin", ""):
            with self.assertRaises(CommandError):
                self.lancer(dict(self.ENV, DJANGO_SUPERUSER_PASSWORD=mdp))
        self.assertFalse(User.objects.exists())


class SanteEtMediaTests(BaseFleetTest):
    def test_sante(self):
        r = self.client.get(reverse("fleet:sante"))
        self.assertEqual((r.status_code, r.content), (200, b"ok"))

    def test_media_reserve_aux_utilisateurs_connectes(self):
        os.makedirs(os.path.join(MEDIA_TESTS, "captures"), exist_ok=True)
        with open(os.path.join(MEDIA_TESTS, "captures", "recu.png"), "wb") as f:
            f.write(png_bytes())
        url = reverse("fleet:media", args=["captures/recu.png"])
        self.assertEqual(url, "/media/captures/recu.png")
        anonyme = self.client.get(url)
        self.assertEqual(anonyme.status_code, 302)
        self.assertIn("/login/", anonyme["Location"])
        self.login("PERCEPTEUR")
        r = self.client.get(url)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "image/png")
        self.assertIn("private", r["Cache-Control"])
        # pas de sortie du dossier media : requête refusée (400 ou 404), jamais le fichier
        for chemin in ("/media/../fleet_manager/settings.py", "/media/%2e%2e/manage.py",
                       "/media/..%2f..%2fmanage.py"):
            r = self.client.get(chemin)
            self.assertIn(r.status_code, (400, 404), chemin)
            self.assertNotIn(b"SECRET_KEY", getattr(r, "content", b""))
