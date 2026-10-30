import re

import pytest
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient
from rest_framework.throttling import ScopedRateThrottle

User = get_user_model()
PASSWORD = "lamp-room-dawn-17"


@pytest.fixture(autouse=True)
def fresh_throttles():
    cache.clear()


@pytest.fixture
def alice():
    return User.objects.create_user(username="alice", email="alice@example.com", password=PASSWORD)


def signed_in(user):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Token {Token.objects.get_or_create(user=user)[0].key}")
    return client


def signup(client, **overrides):
    body = {"username": "bob", "email": "bob@example.com", "password": PASSWORD, "display_name": "Bob"}
    return client.post("/api/auth/signup/", {**body, **overrides}, format="json")


@pytest.mark.django_db
def test_signup_returns_a_working_token_and_creates_the_profile():
    response = signup(APIClient())
    assert response.status_code == 201

    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Token {response.data['token']}")
    me = client.get("/api/auth/me/").data
    assert (me["username"], me["email"], me["display_name"], me["is_admin"]) == ("bob", "bob@example.com", "Bob", False)
    assert client.get("/api/productions/").data == []  # a new user starts with nothing


@pytest.mark.django_db
def test_signup_rejects_taken_names_emails_and_weak_passwords(alice):
    client = APIClient()
    assert "username" in signup(client, username="ALICE").data  # case-insensitive
    assert "email" in signup(client, email="Alice@Example.com").data
    assert "password" in signup(client, password="12345678").data  # too common, all digits
    assert "password" in signup(client, password="bob").data  # too short
    assert signup(client, username="bad name!").status_code == 400
    assert User.objects.count() == 1


@pytest.mark.django_db
def test_login_and_logout(alice):
    client = APIClient()
    assert client.post("/api/auth/token/", {"username": "alice", "password": "wrong"}).status_code == 400
    token = client.post("/api/auth/token/", {"username": "alice", "password": PASSWORD}).data["token"]

    client.credentials(HTTP_AUTHORIZATION=f"Token {token}")
    assert client.post("/api/auth/logout/").status_code == 204
    assert client.get("/api/auth/me/").status_code == 401


@pytest.mark.django_db
def test_profile_update_merges_preferences_and_guards_email(alice):
    User.objects.create_user(username="carol", email="carol@example.com", password=PASSWORD)
    client = signed_in(alice)

    client.patch("/api/auth/me/", {"preferences": {"reduced_motion": True}}, format="json")
    me = client.patch("/api/auth/me/", {"display_name": "Alice SM", "preferences": {"theme": "dark"}}, format="json").data
    assert me["display_name"] == "Alice SM"
    assert me["preferences"] == {"reduced_motion": True, "theme": "dark"}

    assert client.patch("/api/auth/me/", {"email": "CAROL@example.com"}, format="json").status_code == 400
    assert client.patch("/api/auth/me/", {"preferences": ["x"]}, format="json").status_code == 400
    # Username and admin status are not the user's to change.
    client.patch("/api/auth/me/", {"username": "root", "is_admin": True}, format="json")
    alice.refresh_from_db()
    assert (alice.username, alice.is_staff) == ("alice", False)


@pytest.mark.django_db
def test_password_change_needs_the_current_password_and_replaces_the_token(alice):
    client = signed_in(alice)
    old_token = Token.objects.get(user=alice).key
    url = "/api/auth/password/"

    assert client.post(url, {"current_password": "nope", "new_password": "fly-tower-42-a"}).status_code == 400
    assert client.post(url, {"current_password": PASSWORD, "new_password": "alice"}).status_code == 400

    response = client.post(url, {"current_password": PASSWORD, "new_password": "fly-tower-42-a"})
    assert response.status_code == 200
    assert response.data["token"] != old_token
    assert not Token.objects.filter(key=old_token).exists()  # other devices are signed out
    alice.refresh_from_db()
    assert alice.check_password("fly-tower-42-a")


def reset_link(message):
    return re.search(r"/reset-password/([^/\s]+)/([^/\s]+)", message.body).groups()


@pytest.mark.django_db
def test_password_reset_by_email(alice):
    client = APIClient()
    Token.objects.create(user=alice)
    assert client.post("/api/auth/password-reset/", {"email": "ALICE@example.com"}).status_code == 204
    assert len(mail.outbox) == 1 and mail.outbox[0].to == ["alice@example.com"]
    uid, token = reset_link(mail.outbox[0])

    confirm = "/api/auth/password-reset/confirm/"
    assert client.post(confirm, {"uid": uid, "token": "bad-token", "new_password": "new-pass-9876"}).status_code == 400
    assert client.post(confirm, {"uid": uid, "token": token, "new_password": "123"}).status_code == 400
    assert client.post(confirm, {"uid": uid, "token": token, "new_password": "new-pass-9876"}).status_code == 204

    alice.refresh_from_db()
    assert alice.check_password("new-pass-9876")
    assert not Token.objects.filter(user=alice).exists()
    # The link works once: the token is tied to the old password hash.
    assert client.post(confirm, {"uid": uid, "token": token, "new_password": "again-pass-5432"}).status_code == 400


@pytest.mark.django_db
def test_password_reset_does_not_reveal_who_has_an_account(alice):
    alice.is_active = False
    alice.save()
    client = APIClient()
    assert client.post("/api/auth/password-reset/", {"email": "nobody@example.com"}).status_code == 204
    assert client.post("/api/auth/password-reset/", {"email": "alice@example.com"}).status_code == 204  # suspended
    assert mail.outbox == []


@pytest.mark.django_db
def test_auth_endpoints_are_throttled(monkeypatch):
    # DRF reads the rates once at import, so patch the class rather than settings.
    monkeypatch.setattr(ScopedRateThrottle, "THROTTLE_RATES", {"auth": "3/min"})
    client = APIClient()
    for url in ("/api/auth/token/", "/api/auth/signup/", "/api/auth/password-reset/"):
        cache.clear()
        statuses = [client.post(url, {}).status_code for _ in range(4)]
        assert statuses[:3] == [400, 400, 400] and statuses[3] == 429, url
