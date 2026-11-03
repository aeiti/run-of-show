import os
import sys

from django.apps import AppConfig
from django.conf import settings


class ShowsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'shows'

    def ready(self):
        from . import console  # noqa: F401  (connects the settings signals)
        from .startup import serving_port, wake_in_background

        # Start the console listeners as soon as the server is up (see startup.py).
        port = serving_port(sys.argv, os.environ)
        if settings.EOS_LISTENERS and port is not None:
            wake_in_background(port)
