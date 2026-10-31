from django.conf import settings
from django.db import models


class Profile(models.Model):
    """What a user can change about themselves beyond Django's own fields.

    Created on first use (``profile_for``), so users made by ``createsuperuser``
    or the admin don't need one up front.
    """

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile")
    display_name = models.CharField(max_length=100, blank=True)
    # Display preferences, e.g. {"reduced_motion": true}. Free-form so the
    # settings page (#7) can add keys without a migration.
    preferences = models.JSONField(default=dict, blank=True)

    def __str__(self):
        return self.display_name or self.user.get_username()


def profile_for(user):
    return Profile.objects.get_or_create(user=user)[0]


def display_name(user):
    """The user's display name, or "" when they haven't set one (or have no profile yet)."""
    try:
        return user.profile.display_name
    except Profile.DoesNotExist:
        return ""


def shown_name(user):
    """The name to print for a user: their display name, else their username; "" for nobody."""
    return (display_name(user) or user.get_username()) if user else ""
