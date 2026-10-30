from django.contrib import admin
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from accounts.views import AdminUserViewSet
from shows.views import (
    CueNoteViewSet,
    CueViewSet,
    MembershipViewSet,
    ProductionFileViewSet,
    ProductionViewSet,
    RunViewSet,
)

router = DefaultRouter()
router.register("productions", ProductionViewSet, basename="production")
router.register("cues", CueViewSet, basename="cue")
router.register("runs", RunViewSet, basename="run")
router.register("cue-notes", CueNoteViewSet, basename="cue-note")
router.register("files", ProductionFileViewSet, basename="file")
router.register("memberships", MembershipViewSet, basename="membership")
router.register("admin/users", AdminUserViewSet, basename="admin-user")

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/auth/", include("accounts.urls")),
    path("api/", include(router.urls)),
]
