"""Routage principal : admin, authentification et application fleet."""
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("login/", auth_views.LoginView.as_view(template_name="login.html",
                                                redirect_authenticated_user=True),
         name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    # L'application occupe tout le site : pas de préfixe "fleet/".
    # Les fichiers envoyés (media/) y sont servis aux seuls utilisateurs connectés.
    path("", include("fleet.urls")),
]
