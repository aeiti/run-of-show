"""Checks on uploaded production files and logos, and cleanup of stored files.

Files are stored through Django's default storage (the filesystem in
development, S3 when it's configured; see settings.py) and are only ever
served through the API, which checks the user's role first. Nothing is
published at a media URL.
"""

import mimetypes

from django.db import transaction

# A logo's type is read from its first bytes, not trusted from the upload.
# SVG is left out: it can carry script, and these are served from the API.
IMAGE_SIGNATURES = [
    (b"\x89PNG\r\n\x1a\n", "image/png", "png"),
    (b"\xff\xd8\xff", "image/jpeg", "jpg"),
    (b"GIF87a", "image/gif", "gif"),
    (b"GIF89a", "image/gif", "gif"),
]


def image_type(head):
    """(content type, extension) of a PNG, JPEG, GIF or WebP from its first bytes, or None."""
    for signature, content_type, ext in IMAGE_SIGNATURES:
        if head.startswith(signature):
            return content_type, ext
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp", "webp"
    return None


def is_pdf(head):
    return head.startswith(b"%PDF-")


def read_head(upload, size=16):
    upload.seek(0)
    head = upload.read(size)
    upload.seek(0)
    return head


def content_type_for(name):
    return mimetypes.guess_type(name)[0] or "application/octet-stream"


def delete_stored(field_file):
    """Delete a stored file once the transaction commits, so a rollback can't leave a row without its file."""
    if field_file:
        storage, name = field_file.storage, field_file.name
        transaction.on_commit(lambda: storage.delete(name))
