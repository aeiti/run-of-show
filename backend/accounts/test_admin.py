"""User management by admins."""

import pytest
from django.contrib.auth import get_user_model
from django.core import mail
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from accounts.tests import PASSWORD, signed_in
from shows.models import Production

User = get_user_model()
URL = "/api/admin/users/"


@pytest.fixture
def admin():
    return User.objects.create_user(username="root", email="root@example.com", password=PASSWORD, is_staff=True)


@pytest.fixture
def bob():
    return User.objects.create_user(username="bob", email="bob@example.com", password=PASSWORD)


@pytest.mark.django_db
def test_only_admins_can_manage_users(admin, bob):
    assert signed_in(bob).get(URL).status_code == 403
    assert signed_in(bob).patch(f"{URL}{admin.id}/", {"is_active": False}, format="json").status_code == 403
    assert APIClient().get(URL).status_code == 401
    assert signed_in(admin).get(URL).status_code == 200


@pytest.mark.django_db
def test_list_search_and_production_counts(admin, bob):
    Production.objects.create(owner=bob, name="Show")
    client = signed_in(admin)
    listed = {u["username"]: u for u in client.get(URL).data}
    assert (listed["bob"]["productions_owned"], listed["bob"]["is_admin"], listed["root"]["is_admin"]) == (1, False, True)
    assert "password" not in listed["bob"]
    assert [u["username"] for u in client.get(URL, {"q": "BOB@"}).data] == ["bob"]


@pytest.mark.django_db
def test_admin_creates_a_user_who_can_sign_in(admin):
    client = signed_in(admin)
    body = {"username": "carol", "email": "carol@example.com", "display_name": "Carol", "password": "follow-spot-99"}
    assert client.post(URL, {**body, "password": ""}, format="json").status_code == 400
    assert client.post(URL, {**body, "password": None}, format="json").status_code == 400
    assert client.post(URL, {k: v for k, v in body.items() if k != "password"}, format="json").status_code == 400

    created = client.post(URL, body, format="json")
    assert created.status_code == 201
    assert (created.data["display_name"], created.data["is_admin"]) == ("Carol", False)
    login = APIClient().post("/api/auth/token/", {"username": "carol", "password": "follow-spot-99"})
    assert login.status_code == 200


@pytest.mark.django_db
def test_suspending_signs_the_user_out_and_keeps_their_productions(admin, bob):
    Production.objects.create(owner=bob, name="Show")
    bob_client = signed_in(bob)
    response = signed_in(admin).patch(f"{URL}{bob.id}/", {"is_active": False}, format="json")
    assert response.status_code == 200 and response.data["is_active"] is False

    assert not Token.objects.filter(user=bob).exists()
    assert bob_client.get("/api/productions/").status_code == 401
    assert APIClient().post("/api/auth/token/", {"username": "bob", "password": PASSWORD}).status_code == 400
    assert Production.objects.filter(owner=bob).exists()

    signed_in(admin).patch(f"{URL}{bob.id}/", {"is_active": True}, format="json")
    assert APIClient().post("/api/auth/token/", {"username": "bob", "password": PASSWORD}).status_code == 200


@pytest.mark.django_db
def test_promote_rename_and_set_password(admin, bob):
    client = signed_in(admin)
    updated = client.patch(
        f"{URL}{bob.id}/", {"is_admin": True, "display_name": "Bob SM", "password": "new-gel-string-4"}, format="json"
    ).data
    assert (updated["is_admin"], updated["display_name"]) == (True, "Bob SM")
    bob.refresh_from_db()
    assert bob.is_staff and bob.check_password("new-gel-string-4") and not bob.is_superuser
    assert client.patch(f"{URL}{bob.id}/", {"username": "ROOT"}, format="json").status_code == 400


@pytest.mark.django_db
def test_admin_cannot_lock_themselves_out(admin):
    client = signed_in(admin)
    assert client.patch(f"{URL}{admin.id}/", {"is_admin": False}, format="json").status_code == 400
    assert client.patch(f"{URL}{admin.id}/", {"is_active": False}, format="json").status_code == 400
    assert client.delete(f"{URL}{admin.id}/").status_code == 400
    admin.refresh_from_db()
    assert admin.is_staff and admin.is_active


@pytest.mark.django_db
def test_delete_is_refused_while_the_user_owns_productions(admin, bob):
    client = signed_in(admin)
    show = Production.objects.create(owner=bob, name="Show")
    refused = client.delete(f"{URL}{bob.id}/")
    assert refused.status_code == 400 and "Suspend" in refused.data["detail"]
    assert Production.objects.filter(pk=show.pk).exists()

    show.delete()
    assert client.delete(f"{URL}{bob.id}/").status_code == 204
    assert not User.objects.filter(pk=bob.pk).exists()


@pytest.mark.django_db
def test_admin_can_send_a_reset_link(admin, bob):
    client = signed_in(admin)
    assert client.post(f"{URL}{bob.id}/send-reset/").status_code == 204
    assert mail.outbox[0].to == ["bob@example.com"] and "/reset-password/" in mail.outbox[0].body

    bob.is_active = False
    bob.save()
    assert client.post(f"{URL}{bob.id}/send-reset/").status_code == 400


@pytest.mark.django_db
def test_admin_sets_any_non_empty_password(admin, bob):
    client = signed_in(admin)
    # Short, common, all digits, like the username: self-service would refuse each.
    for password in ("1", "password", "12345678", "bob", " "):
        assert client.patch(f"{URL}{bob.id}/", {"password": password}, format="json").status_code == 200, password
        bob.refresh_from_db()
        assert bob.check_password(password)

    assert client.patch(f"{URL}{bob.id}/", {"password": None}, format="json").status_code == 400
    assert client.patch(f"{URL}{bob.id}/", {"password": ""}, format="json").status_code == 400
    bob.refresh_from_db()
    assert bob.check_password(" ")
    # Leaving the password out keeps it.
    assert client.patch(f"{URL}{bob.id}/", {"display_name": "Bob"}, format="json").status_code == 200
    bob.refresh_from_db()
    assert bob.check_password(" ")

    created = client.post(URL, {"username": "dan", "email": None, "password": "x"}, format="json")
    assert created.status_code == 201
    assert APIClient().post("/api/auth/token/", {"username": "dan", "password": "x"}).status_code == 200


@pytest.mark.django_db
def test_admin_sets_any_well_formed_email_or_none(admin, bob):
    client = signed_in(admin)
    url = f"{URL}{bob.id}/"

    # Shared with another account is fine for an admin.
    assert client.patch(url, {"email": "ROOT@example.com"}, format="json").data["email"] == "ROOT@example.com"
    for cleared in (None, ""):
        assert client.patch(url, {"email": cleared}, format="json").data["email"] is None
        bob.refresh_from_db()
        assert bob.email == ""

    for bad in ("not-an-email", "bob@", "@example.com", "bob example.com"):
        assert client.patch(url, {"email": bad}, format="json").status_code == 400, bad
    # No email means no reset link.
    assert client.post(f"{url}send-reset/").status_code == 400


@pytest.mark.django_db
def test_user_with_an_admin_set_shared_email_can_still_save_their_profile(admin, bob):
    signed_in(admin).patch(f"{URL}{bob.id}/", {"email": "root@example.com"}, format="json")
    me = signed_in(bob).patch("/api/auth/me/", {"display_name": "Bob", "email": "root@example.com"}, format="json")
    assert me.status_code == 200
    # Choosing someone else's email themselves is still refused.
    User.objects.create_user(username="carol", email="carol@example.com", password=PASSWORD)
    assert signed_in(bob).patch("/api/auth/me/", {"email": "carol@example.com"}, format="json").status_code == 400
