# -*- coding: utf-8 -*-
"""Convertit les montants déjà en base d'une monnaie à une autre (ex. FCFA -> FC).

Simulation par défaut ; ajouter --appliquer pour écrire en base.

    python manage.py convertir_monnaie --taux 4.05            # aperçu
    python manage.py convertir_monnaie --taux 4.05 --appliquer

Le taux est le nombre de nouvelles unités pour 1 ancienne (FC pour 1 FCFA) :
à relever le jour de la bascule. Les montants sont arrondis à l'unité.
"""
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Sum

from fleet.models import Depense, Recette

CHAMPS = [(Recette, ["montant_verse", "montant_fixe"]), (Depense, ["montant"])]


class Command(BaseCommand):
    help = "Convertit les montants (recettes, dépenses) avec un taux de change."

    def add_arguments(self, parser):
        parser.add_argument("--taux", required=True,
                            help="Nouvelles unités pour 1 ancienne (ex. 4.05 FC pour 1 FCFA).")
        parser.add_argument("--appliquer", action="store_true",
                            help="Écrit en base (sinon simple aperçu).")

    def handle(self, *args, taux, appliquer, **options):
        try:
            t = Decimal(taux.replace(",", "."))
        except InvalidOperation:
            raise CommandError("Taux invalide.")
        if t <= 0:
            raise CommandError("Le taux doit être positif.")

        def conv(v):
            return int((Decimal(v) * t).quantize(Decimal("1"), rounding=ROUND_HALF_UP))

        for model, champs in CHAMPS:
            totaux = model.objects.aggregate(**{c: Sum(c) for c in champs})
            for c in champs:
                avant = totaux[c] or 0
                self.stdout.write(f"{model.__name__}.{c} : total {avant:,} -> ~{conv(avant):,}"
                                  .replace(",", " "))

        if not appliquer:
            self.stdout.write(self.style.WARNING("Aperçu seulement : relancez avec --appliquer."))
            return

        with transaction.atomic():
            n = 0
            for model, champs in CHAMPS:
                objs = list(model.objects.only("id", *champs))
                for o in objs:
                    for c in champs:
                        setattr(o, c, conv(getattr(o, c)))
                model.objects.bulk_update(objs, champs, batch_size=500)
                n += len(objs)
        self.stdout.write(self.style.SUCCESS(f"{n} ligne(s) converties au taux {t}."))
