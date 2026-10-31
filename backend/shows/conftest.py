from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model

from shows.models import Cue, Production, Run


@pytest.fixture(autouse=True)
def no_console_listeners(settings):
    # Tests that listen make their own Supervisor; the server's stays idle.
    settings.EOS_LISTENERS = False


@pytest.fixture
def make_user():
    def _make(username):
        return get_user_model().objects.create_user(username=username, password="pw-for-tests")

    return _make


@pytest.fixture
def show(make_user):
    """Alice's production: cues 1, 2, 12, 12.5, 100 (created out of order) and one run."""
    owner = make_user("alice")
    production = Production.objects.create(owner=owner, name="Show A")
    cues = {
        n: Cue.objects.create(production=production, number=Decimal(n), label=f"Cue {n}")
        for n in ["100", "12.5", "1", "12", "2"]
    }
    run = Run.objects.create(production=production, label="Preview 1")
    return SimpleNamespace(owner=owner, production=production, cues=cues, run=run)
