"""Variables communes à tous les gabarits."""
from django.conf import settings


def fleet_settings(request):
    # Note : la variable `debug` de Django n'est remplie que si l'IP cliente est
    # dans INTERNAL_IPS ; on expose donc nos propres drapeaux, plus fiables.
    return {
        "show_demo_accounts": settings.SHOW_DEMO_ACCOUNTS,
        "show_dev_notes": settings.DEBUG,
        "devise": settings.FLEET_DEVISE,
    }
