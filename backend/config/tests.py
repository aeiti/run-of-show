import pytest
from django.contrib.auth import get_user_model
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

User = get_user_model()


def signed_in():
    user = User.objects.create_user(username="sm", password="lamp-room-dawn-17")
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Token {Token.objects.create(user=user).key}")
    return client


@pytest.mark.django_db
def test_network_lists_lan_hosts(settings):
    settings.LAN_HOSTS = ["adams-macbook-pro.local", "192.168.1.241"]
    res = signed_in().get("/api/network/")
    assert res.status_code == 200
    assert res.json() == {"hosts": ["adams-macbook-pro.local", "192.168.1.241"]}


@pytest.mark.django_db
def test_network_empty_without_lan_hosts(settings):
    settings.LAN_HOSTS = []
    assert signed_in().get("/api/network/").json() == {"hosts": []}


@pytest.mark.django_db
def test_network_needs_sign_in():
    assert APIClient().get("/api/network/").status_code == 401
