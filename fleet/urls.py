from django.urls import path

from . import views

app_name = "fleet"

urlpatterns = [
    path("", views.home, name="home"),
    path("percepteur/", views.percepteur, name="percepteur"),
    path("chauffeur/", views.chauffeur, name="chauffeur"),
    path("technique/", views.technique, name="technique"),
    path("rh/", views.rh, name="rh"),
    path("finance/", views.finance, name="finance"),
    path("dg/", views.dg, name="dg"),
    path("mot-de-passe/", views.ChangerMotDePasse.as_view(), name="mot_de_passe"),
    path("sante/", views.sante, name="sante"),
    path("media/<path:chemin>", views.media_protege, name="media"),
]
