"""
apps/inorder/apps.py
====================
AppConfig for the inorder app.

The ready() method is the correct place to connect Django signals.
Connecting signals here (rather than at module import time) ensures:
  1. All models are fully loaded before signal receivers reference them.
  2. The signal is registered exactly once (no duplicate handlers on
     Django's dev-server autoreload).
"""

from django.apps import AppConfig


class InOrderConfig(AppConfig):
    name            = 'apps.inorder'
    label           = 'inorder'
    verbose_name    = 'Inbound Orders'
    default_auto_field = 'django.db.models.BigAutoField'

    def ready(self):
        # Importing the signals module here registers all @receiver decorators.
        import apps.inorder.signals  # noqa: F401
