import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from shows.models import Membership, ProductionFile

PDF = b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\n%%EOF\n"


@pytest.fixture(autouse=True)
def media(settings, tmp_path):
    """Store uploads in a temporary folder, never the repo's media folder."""
    settings.MEDIA_ROOT = tmp_path
    return tmp_path


def client_for(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


def upload(client, production, name="show.esf", content=b"eos show", kind="showfile"):
    return client.post(
        f"/api/productions/{production.id}/files/",
        {"file": SimpleUploadedFile(name, content), "kind": kind},
        format="multipart",
    )


def stored(media):
    return sorted(p.read_bytes() for p in media.rglob("*") if p.is_file())


def body(response):
    return b"".join(response.streaming_content)


def member(show, make_user, role):
    user = make_user(role)
    Membership.objects.create(production=show.production, user=user, role=role)
    return user


@pytest.mark.django_db
def test_upload_list_and_download(show, media):
    client = client_for(show.owner)

    response = upload(client, show.production, "Act 1.esf", b"eos show")

    assert response.status_code == 201
    f = response.data
    assert (f["kind"], f["name"], f["version"], f["size"], f["uploaded_by"]) == ("showfile", "Act 1.esf", 1, 8, "alice")
    assert client.get(f"/api/productions/{show.production.id}/files/").data == [f]
    assert stored(media) == [b"eos show"]

    download = client.get(f"/api/files/{f['id']}/download/")
    assert download.status_code == 200
    assert body(download) == b"eos show"
    assert download["Content-Disposition"] == 'attachment; filename="Act 1.esf"'


@pytest.mark.django_db
def test_a_file_from_a_user_never_renders_as_a_page(show):
    client = client_for(show.owner)
    f = upload(client, show.production, "notes.html", b"<script>alert(1)</script>", kind="other").data

    download = client.get(f"/api/files/{f['id']}/download/")

    assert download["Content-Disposition"].startswith("attachment;")
    assert download["X-Content-Type-Options"] == "nosniff"


@pytest.mark.django_db
def test_the_same_name_and_kind_adds_a_version(show):
    client = client_for(show.owner)
    first = upload(client, show.production, "show.esf", b"version one").data
    second = upload(client, show.production, "show.esf", b"version two").data
    # Same name, different kind: a file of its own.
    other = upload(client, show.production, "show.esf", b"something else", kind="other").data

    assert (first["version"], second["version"], other["version"]) == (1, 2, 1)
    listed = client.get(f"/api/productions/{show.production.id}/files/").data
    assert [(f["kind"], f["version"]) for f in listed] == [("other", 1), ("showfile", 2), ("showfile", 1)]
    assert body(client.get(f"/api/files/{first['id']}/download/")) == b"version one"
    assert body(client.get(f"/api/files/{second['id']}/download/")) == b"version two"


@pytest.mark.django_db
def test_a_script_must_be_a_pdf(show, media):
    client = client_for(show.owner)

    refused = upload(client, show.production, "script.pdf", b"not really a pdf", kind="script")
    assert refused.status_code == 400
    assert "PDF" in str(refused.data["file"])

    accepted = upload(client, show.production, "script.pdf", PDF, kind="script")
    assert accepted.status_code == 201
    assert accepted.data["content_type"] == "application/pdf"
    assert stored(media) == [PDF]


@pytest.mark.django_db
def test_files_over_the_limit_are_refused(show, media, settings):
    settings.PRODUCTION_FILE_MAX_SIZE = 10
    client = client_for(show.owner)

    assert upload(client, show.production, content=b"x" * 10).status_code == 201
    refused = upload(client, show.production, content=b"x" * 11)

    assert refused.status_code == 400
    assert "up to" in str(refused.data["file"])
    assert ProductionFile.objects.count() == 1
    assert stored(media) == [b"x" * 10]


@pytest.mark.django_db
def test_empty_files_and_unknown_kinds_are_refused(show):
    client = client_for(show.owner)
    assert upload(client, show.production, content=b"").status_code == 400
    assert upload(client, show.production, kind="costume").status_code == 400
    assert ProductionFile.objects.count() == 0


@pytest.mark.django_db
def test_a_path_in_the_name_is_dropped(show, media):
    f = upload(client_for(show.owner), show.production, "../../etc/show.esf").data
    assert f["name"] == "show.esf"
    assert [p.relative_to(media).parts[:3] for p in media.rglob("*") if p.is_file()] == [
        ("productions", str(show.production.id), "files")
    ]


@pytest.mark.django_db
@pytest.mark.parametrize("role", ["viewer", "operator"])
def test_viewers_and_operators_can_download_but_not_upload_or_delete(show, make_user, role):
    f = upload(client_for(show.owner), show.production).data
    client = client_for(member(show, make_user, role))

    assert client.get(f"/api/productions/{show.production.id}/files/").status_code == 200
    assert body(client.get(f"/api/files/{f['id']}/download/")) == b"eos show"
    assert upload(client, show.production).status_code == 403
    assert client.delete(f"/api/files/{f['id']}/").status_code == 403
    assert ProductionFile.objects.count() == 1


@pytest.mark.django_db
def test_stage_managers_can_upload_and_delete(show, make_user, django_capture_on_commit_callbacks):
    client = client_for(member(show, make_user, "stage_manager"))
    f = upload(client, show.production).data
    with django_capture_on_commit_callbacks(execute=True):
        assert client.delete(f"/api/files/{f['id']}/").status_code == 204
    assert ProductionFile.objects.count() == 0


@pytest.mark.django_db
def test_strangers_get_404_and_signed_out_users_401(show, make_user):
    f = upload(client_for(show.owner), show.production).data
    stranger = client_for(make_user("mallory"))

    assert stranger.get(f"/api/productions/{show.production.id}/files/").status_code == 404
    assert upload(stranger, show.production).status_code == 404
    assert stranger.get(f"/api/files/{f['id']}/").status_code == 404
    assert stranger.get(f"/api/files/{f['id']}/download/").status_code == 404
    assert stranger.delete(f"/api/files/{f['id']}/").status_code == 404
    assert APIClient().get(f"/api/files/{f['id']}/download/").status_code == 401
    assert ProductionFile.objects.count() == 1


@pytest.mark.django_db
def test_deleting_a_version_deletes_its_stored_file(show, media, django_capture_on_commit_callbacks):
    client = client_for(show.owner)
    first = upload(client, show.production, content=b"version one").data
    upload(client, show.production, content=b"version two")

    with django_capture_on_commit_callbacks(execute=True):
        assert client.delete(f"/api/files/{first['id']}/").status_code == 204

    assert stored(media) == [b"version two"]
    assert [f["version"] for f in client.get(f"/api/productions/{show.production.id}/files/").data] == [2]


@pytest.mark.django_db
def test_deleting_the_production_deletes_its_stored_files(show, media, django_capture_on_commit_callbacks):
    client = client_for(show.owner)
    upload(client, show.production, "show.esf", b"one")
    upload(client, show.production, "show.esf", b"two")
    upload(client, show.production, "script.pdf", PDF, kind="script")
    assert len(stored(media)) == 3

    with django_capture_on_commit_callbacks(execute=True):
        assert client.delete(f"/api/productions/{show.production.id}/").status_code == 204

    assert stored(media) == []
    assert ProductionFile.objects.count() == 0


# Production logos

PNG = b"\x89PNG\r\n\x1a\n" + b"png pixels"
JPEG = b"\xff\xd8\xff\xe0" + b"jpeg pixels"


def put_logo(client, production, content=PNG, name="logo.png"):
    return client.put(
        f"/api/productions/{production.id}/logo/", {"file": SimpleUploadedFile(name, content)}, format="multipart"
    )


@pytest.mark.django_db
def test_a_logo_is_uploaded_shown_and_fetched(show, media):
    client = client_for(show.owner)
    assert client.get(f"/api/productions/{show.production.id}/").data["logo"] is None

    response = put_logo(client, show.production)

    assert response.status_code == 200
    token = response.data["logo"]
    assert token
    assert client.get("/api/productions/").data[0]["logo"] == token
    image = client.get(f"/api/productions/{show.production.id}/logo/")
    assert body(image) == PNG
    assert image["Content-Type"] == "image/png"
    assert stored(media) == [PNG]


@pytest.mark.django_db
def test_replacing_a_logo_deletes_the_old_image(show, media, django_capture_on_commit_callbacks):
    client = client_for(show.owner)
    first = put_logo(client, show.production).data["logo"]

    with django_capture_on_commit_callbacks(execute=True):
        second = put_logo(client, show.production, JPEG, "logo.jpg").data["logo"]

    assert second != first
    assert stored(media) == [JPEG]
    assert client.get(f"/api/productions/{show.production.id}/logo/")["Content-Type"] == "image/jpeg"


@pytest.mark.django_db
def test_removing_a_logo(show, media, django_capture_on_commit_callbacks):
    client = client_for(show.owner)
    put_logo(client, show.production)

    with django_capture_on_commit_callbacks(execute=True):
        response = client.delete(f"/api/productions/{show.production.id}/logo/")

    assert (response.status_code, response.data["logo"]) == (200, None)
    assert stored(media) == []
    assert client.get(f"/api/productions/{show.production.id}/logo/").status_code == 404


@pytest.mark.django_db
@pytest.mark.parametrize(
    "content, name",
    [
        (b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>', "logo.svg"),
        (b"just text", "logo.png"),
        (PDF, "logo.gif"),
    ],
)
def test_a_logo_must_be_an_image(show, media, content, name, django_capture_on_commit_callbacks):
    client = client_for(show.owner)
    put_logo(client, show.production)

    with django_capture_on_commit_callbacks(execute=True):
        refused = put_logo(client, show.production, content, name)

    assert refused.status_code == 400
    assert "PNG, JPEG, GIF or WebP" in str(refused.data["file"])
    # The logo it had is untouched.
    assert stored(media) == [PNG]
    assert body(client.get(f"/api/productions/{show.production.id}/logo/")) == PNG


@pytest.mark.django_db
def test_logos_over_the_limit_are_refused(show, media, settings):
    settings.PRODUCTION_LOGO_MAX_SIZE = len(PNG)
    client = client_for(show.owner)

    refused = put_logo(client, show.production, PNG + b"!")
    assert refused.status_code == 400
    assert "up to" in str(refused.data["file"])
    assert stored(media) == []
    assert put_logo(client, show.production, PNG).status_code == 200


@pytest.mark.django_db
def test_any_role_sees_the_logo_but_only_editors_change_it(show, make_user):
    put_logo(client_for(show.owner), show.production)
    viewer = client_for(member(show, make_user, "viewer"))
    operator = client_for(member(show, make_user, "operator"))
    manager = client_for(member(show, make_user, "stage_manager"))
    stranger = client_for(make_user("mallory"))

    assert body(viewer.get(f"/api/productions/{show.production.id}/logo/")) == PNG
    assert put_logo(viewer, show.production, JPEG).status_code == 403
    assert put_logo(operator, show.production, JPEG).status_code == 403
    assert viewer.delete(f"/api/productions/{show.production.id}/logo/").status_code == 403
    assert stranger.get(f"/api/productions/{show.production.id}/logo/").status_code == 404
    assert put_logo(stranger, show.production, JPEG).status_code == 404
    assert put_logo(manager, show.production, JPEG).status_code == 200


@pytest.mark.django_db
def test_deleting_the_production_deletes_its_logo(show, media, django_capture_on_commit_callbacks):
    client = client_for(show.owner)
    put_logo(client, show.production)

    with django_capture_on_commit_callbacks(execute=True):
        client.delete(f"/api/productions/{show.production.id}/")

    assert stored(media) == []


@pytest.mark.django_db
def test_the_logo_goes_with_a_backup_and_a_copy(show, media):
    client = client_for(show.owner)
    put_logo(client, show.production)
    upload(client, show.production)
    exported = client.get(f"/api/productions/{show.production.id}/export/").json()

    imported = client.post("/api/productions/import/", exported, format="json")
    copy = client.post(f"/api/productions/{show.production.id}/duplicate/", {}, format="json")

    for made in (imported, copy):
        assert made.status_code == 201
        assert made.data["logo"]
        assert body(client.get(f"/api/productions/{made.data['id']}/logo/")) == PNG
        # Scripts and showfiles stay behind.
        assert client.get(f"/api/productions/{made.data['id']}/files/").data == []
    # Each production has its own copy of the image.
    assert stored(media) == sorted([PNG, PNG, PNG, b"eos show"])


@pytest.mark.django_db
def test_a_backup_without_a_logo_still_imports_and_a_bad_one_is_refused(show):
    client = client_for(show.owner)
    exported = client.get(f"/api/productions/{show.production.id}/export/").json()
    assert "logo" not in exported
    assert client.post("/api/productions/import/", exported, format="json").data["logo"] is None

    bad = {**exported, "logo": {"data": "not base64!"}}
    assert "base64" in str(client.post("/api/productions/import/", bad, format="json").data["logo"])
    text = {**exported, "logo": {"data": "aGVsbG8="}}
    assert "PNG" in str(client.post("/api/productions/import/", text, format="json").data["logo"])
