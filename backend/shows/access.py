"""Who can see and change a production.

A user sees a production they own or are a member of; anyone else gets a 404,
as if it didn't exist. Within a production, what they may do depends on their
role. Reading is open to every role; each write names the capability it needs
(``capabilities`` on the viewset), and a member without it gets a 403.
"""

from django.db.models import OuterRef, Q, Subquery
from rest_framework import permissions

from .models import Membership, Production

OWNER = "owner"
SM, OPERATOR, VIEWER = Membership.Role.STAGE_MANAGER, Membership.Role.OPERATOR, Membership.Role.VIEWER

CAN = {
    "view": {OWNER, SM, OPERATOR, VIEWER},
    # Run the show: GO, BACK, GOTO, RESET, start, rename and end runs.
    "operate": {OWNER, SM, OPERATOR},
    # Change the production's details and its cue list.
    "edit": {OWNER, SM},
    # Add, change and remove members.
    "share": {OWNER, SM},
    "delete": {OWNER},
}


def visible_productions(user):
    """Productions the user owns or is a member of, each annotated with ``member_role``."""
    role = Membership.objects.filter(production=OuterRef("pk"), user=user).values("role")[:1]
    return Production.objects.annotate(member_role=Subquery(role)).filter(
        Q(owner=user) | Q(member_role__isnull=False)
    )


def role_for(production, user):
    if production.owner_id == user.id:
        return OWNER
    if hasattr(production, "member_role"):
        return production.member_role
    return Membership.objects.filter(production=production, user=user).values_list("role", flat=True).first()


def can(production, user, capability):
    return role_for(production, user) in CAN[capability]


class ProductionRole(permissions.BasePermission):
    """Checks the requesting user's role on the object's production.

    Safe methods need "view". Any other action must be listed in the view's
    ``capabilities``; one that isn't is refused, so a new write route can't
    slip through unchecked.
    """

    message = "Your role on this production doesn't allow that."

    def has_object_permission(self, request, view, obj):
        production = obj if isinstance(obj, Production) else obj.production
        if request.method in permissions.SAFE_METHODS:
            capability = "view"
        else:
            capability = getattr(view, "capabilities", {}).get(view.action)
            if capability is None:
                return False
        return can(production, request.user, capability)
