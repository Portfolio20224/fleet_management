# -*- coding: utf-8 -*-
"""Filtres de gabarit."""
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django import template
from django.conf import settings

register = template.Library()

NBSP = "\xa0"


def _milliers(n):
    """25000 -> '25 000' (espaces insécables, indépendant de la locale)."""
    return f"{n:,}".replace(",", NBSP)


@register.filter
def monnaie(value):
    """Formate un montant : 100000 -> 100 000 FC. Valeur invalide -> '—'.

    Le symbole vient de settings.FLEET_DEVISE (franc congolais par défaut).
    """
    if value is None or value == "":
        return "—"
    try:
        n = int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    except (InvalidOperation, TypeError, ValueError):
        return "—"
    return f"{_milliers(n)}{NBSP}{settings.FLEET_DEVISE}"


@register.filter
def get_item(d, key):
    """Accède à une clé de dictionnaire dans un gabarit : kanban|get_item:etape."""
    return (d or {}).get(key, [])


@register.filter
def next_etape(etapes, etape):
    """Retourne l'étape suivante du kanban (ou '' si dernière / inconnue)."""
    lst = list(etapes or [])
    try:
        return lst[lst.index(etape) + 1]
    except (ValueError, IndexError):
        return ""


@register.filter
def zip_lists(a, b):
    """Parcourt deux listes en parallèle : {% for x, y in a|zip_lists:b %}."""
    return list(zip(a or [], b or []))
