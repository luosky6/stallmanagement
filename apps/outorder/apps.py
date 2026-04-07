"""
apps/outorder/apps.py
=====================
AppConfig for the outorder app.

ready() registers the post_save signal on OutOrder so that stock is
automatically deducted on completion and restored on cancellation.
"""

from django.apps import AppConfig


class OutOrderConfig(AppConfig):
    name            = 'apps.outorder'
    label           = 'outorder'
    verbose_name    = 'Outbound Orders'
    default_auto_field = 'django.db.models.BigAutoField'

    def ready(self):
        import apps.outorder.signals  # noqa: F401
