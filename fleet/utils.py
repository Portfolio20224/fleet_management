"""Petits utilitaires partagés."""
import re
import unicodedata


def slug_ascii(texte):
    """« Héritier N'Zi » -> « heritier-nzi » : pour fabriquer des adresses e-mail."""
    t = unicodedata.normalize("NFKD", texte).encode("ascii", "ignore").decode().lower()
    t = re.sub(r"[^a-z0-9]+", "-", t.replace("'", "")).strip("-")
    return t or "x"
