from django.contrib import admin
from django.urls import include, path
from rest_framework.authtoken.views import obtain_auth_token
from rest_framework.routers import DefaultRouter

from shows.views import CueViewSet, ProductionViewSet, RunViewSet

router = DefaultRouter()
router.register("productions", ProductionViewSet, basename="production")
router.register("cues", CueViewSet, basename="cue")
router.register("runs", RunViewSet, basename="run")

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/auth/token/", obtain_auth_token),
    path("api/", include(router.urls)),
]
