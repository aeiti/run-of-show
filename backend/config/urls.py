from django.contrib import admin
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from shows.views import CueViewSet, MembershipViewSet, ProductionViewSet, RunViewSet

router = DefaultRouter()
router.register("productions", ProductionViewSet, basename="production")
router.register("cues", CueViewSet, basename="cue")
router.register("runs", RunViewSet, basename="run")
router.register("memberships", MembershipViewSet, basename="membership")

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/auth/", include("accounts.urls")),
    path("api/", include(router.urls)),
]
