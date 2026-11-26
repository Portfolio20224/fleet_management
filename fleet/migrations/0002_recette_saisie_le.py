# Ajout de l'horodatage de saisie, nécessaire à la règle « une recette par
# chauffeur sur 12 heures ».
from datetime import datetime, time

import django.utils.timezone
from django.db import migrations, models
from django.utils import timezone


def renseigner_recettes_existantes(apps, schema_editor):
    """Les recettes déjà en base n'ont qu'une date : on les place à minuit.

    Sans cela, AddField leur donnerait l'heure de la migration, et tous les
    chauffeurs ayant une recette seraient bloqués pendant 12 heures.
    """
    Recette = apps.get_model("fleet", "Recette")
    for r in Recette.objects.only("id", "date").iterator():
        r.saisie_le = timezone.make_aware(datetime.combine(r.date, time(0, 0)))
        r.save(update_fields=["saisie_le"])


class Migration(migrations.Migration):

    dependencies = [
        ("fleet", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="recette",
            name="saisie_le",
            field=models.DateTimeField(
                db_index=True,
                default=django.utils.timezone.now,
                verbose_name="saisie le",
            ),
        ),
        migrations.RunPython(renseigner_recettes_existantes, migrations.RunPython.noop),
    ]
