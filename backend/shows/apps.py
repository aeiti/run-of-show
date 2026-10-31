from django.apps import AppConfig


class ShowsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'shows'

    def ready(self):
        from . import console  # noqa: F401  (connects the settings signals)
