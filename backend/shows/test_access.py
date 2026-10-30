"""Sharing a production: who sees it, and what each role may do."""

import pytest

from shows.models import Cue, CueEvent, Membership, Production
from shows.tests import act, client_for

ROLES = ["stage_manager", "operator", "viewer"]


def member(show, make_user, role):
    user = make_user(role)
    Membership.objects.create(production=show.production, user=user, role=role)
    return client_for(user)


def attempts(client, show):
    """One request per capability; each returns the response status."""
    prod, cue, run = show.production, show.cues["1"], show.run
    return {
        "view": client.get(f"/api/productions/{prod.id}/cues/").status_code,
        "operate": act(client, run, "go").status_code,
        "edit": client.patch(f"/api/cues/{cue.id}/", {"label": "changed"}, format="json").status_code,
        "share": client.post(f"/api/productions/{prod.id}/members/", {"user": "newcomer"}).status_code,
    }


@pytest.mark.django_db
@pytest.mark.parametrize(
    "role, allowed",
    [
        ("stage_manager", {"view", "operate", "edit", "share"}),
        ("operator", {"view", "operate"}),
        ("viewer", {"view"}),
    ],
)
def test_each_role_can_do_only_its_own_jobs(show, make_user, role, allowed):
    make_user("newcomer")
    statuses = attempts(member(show, make_user, role), show)
    for capability, status in statuses.items():
        if capability in allowed:
            assert status in (200, 201), (capability, status)
        else:
            assert status == 403, (capability, status)
    # Refused writes changed nothing.
    assert CueEvent.objects.exists() == ("operate" in allowed)
    assert Cue.objects.filter(label="changed").exists() == ("edit" in allowed)


@pytest.mark.django_db
@pytest.mark.parametrize("role", ROLES)
def test_only_the_owner_can_delete_the_production(show, make_user, role):
    client = member(show, make_user, role)
    assert client.delete(f"/api/productions/{show.production.id}/").status_code == 403
    assert client_for(show.owner).delete(f"/api/productions/{show.production.id}/").status_code == 204


@pytest.mark.django_db
def test_viewer_cannot_change_the_production_or_runs(show, make_user):
    viewer = member(show, make_user, "viewer")
    prod, run = show.production, show.run
    assert viewer.patch(f"/api/productions/{prod.id}/", {"name": "x"}, format="json").status_code == 403
    assert viewer.post(f"/api/productions/{prod.id}/runs/", {"label": "R2"}).status_code == 403
    assert viewer.post(f"/api/productions/{prod.id}/cues/import/", {"text": "number\n5", "dry_run": "false"}).status_code == 403
    assert viewer.post(f"/api/runs/{run.id}/end/").status_code == 403
    assert viewer.patch(f"/api/runs/{run.id}/", {"notes": "x"}, format="json").status_code == 403
    # Reading, including the exports, is fine.
    assert viewer.get(f"/api/runs/{run.id}/").status_code == 200
    assert viewer.get(f"/api/runs/{run.id}/export/").status_code == 200
    assert viewer.get(f"/api/productions/{prod.id}/cues/export/").status_code == 200


@pytest.mark.django_db
def test_shared_productions_are_listed_with_the_users_role(show, make_user):
    client = member(show, make_user, "operator")
    Production.objects.create(owner=show.owner, name="Not shared")

    listed = client.get("/api/productions/").data
    assert [(p["name"], p["role"], p["owner"]["username"]) for p in listed] == [("Show A", "operator", "alice")]
    assert client_for(show.owner).get(f"/api/productions/{show.production.id}/").data["role"] == "owner"


@pytest.mark.django_db
def test_invite_by_username_or_email(show, make_user):
    owner = client_for(show.owner)
    bob = make_user("bob")
    bob.email = "bob@example.com"
    bob.save()
    make_user("carol")
    url = f"/api/productions/{show.production.id}/members/"

    added = owner.post(url, {"user": "BOB@example.com", "role": "stage_manager"})
    assert added.status_code == 201
    assert (added.data["user"]["username"], added.data["role"]) == ("bob", "stage_manager")
    assert "email" not in added.data["user"]  # collaborators don't see each other's emails
    assert owner.post(url, {"user": "carol"}).data["role"] == "viewer"  # the default

    assert owner.post(url, {"user": "bob"}).status_code == 400  # already on it
    assert owner.post(url, {"user": "alice"}).status_code == 400  # the owner
    assert owner.post(url, {"user": "nobody"}).status_code == 400
    assert owner.post(url, {"user": "carol", "role": "owner"}).status_code == 400

    listing = owner.get(url).data
    assert listing["owner"]["username"] == "alice"
    assert [(m["user"]["username"], m["role"]) for m in listing["members"]] == [("bob", "stage_manager"), ("carol", "viewer")]


@pytest.mark.django_db
def test_changing_roles_and_leaving(show, make_user):
    sm = member(show, make_user, "stage_manager")
    operator = member(show, make_user, "operator")
    op_membership = Membership.objects.get(user__username="operator")
    sm_membership = Membership.objects.get(user__username="stage_manager")
    url = f"/api/memberships/{op_membership.id}/"

    # A stage manager can change roles; an operator can't, not even their own.
    assert operator.patch(url, {"role": "stage_manager"}, format="json").status_code == 403
    assert sm.patch(url, {"role": "viewer"}, format="json").data["role"] == "viewer"
    assert operator.delete(f"/api/memberships/{sm_membership.id}/").status_code == 403

    # Anyone can leave.
    assert operator.delete(url).status_code == 204
    assert operator.get(f"/api/productions/{show.production.id}/").status_code == 404


@pytest.mark.django_db
def test_memberships_of_other_productions_are_invisible(show, make_user):
    other = Production.objects.create(owner=make_user("dave"), name="Other")
    theirs = Membership.objects.create(production=other, user=make_user("erin"), role="viewer")
    owner = client_for(show.owner)
    assert owner.patch(f"/api/memberships/{theirs.id}/", {"role": "stage_manager"}, format="json").status_code == 404
    assert owner.delete(f"/api/memberships/{theirs.id}/").status_code == 404


@pytest.mark.django_db
def test_a_viewer_can_export_and_duplicate_into_their_own_production(show, make_user):
    viewer = member(show, make_user, "viewer")
    prod = show.production
    assert viewer.get(f"/api/productions/{prod.id}/export/").status_code == 200

    copy = viewer.post(f"/api/productions/{prod.id}/duplicate/", {}, format="json")
    assert copy.status_code == 201
    assert (copy.data["role"], copy.data["owner"]["username"]) == ("owner", "viewer")
    # The copy is theirs alone: no memberships come with it.
    assert not Membership.objects.filter(production_id=copy.data["id"]).exists()
