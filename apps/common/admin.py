"""
apps/common/admin.py
====================
Django admin configuration for the common app.

The common app has no standalone models of its own (by design — see the
project structure notes).  This file is therefore intentionally minimal.

What IS registered here
-----------------------
- A customisation of the Django admin site header, title, and index title
  so the admin panel reflects the StallManagement brand.
- Inline documentation on how to extend this file if a future shared model
  is added to common.

What is NOT here
----------------
- No ModelAdmin classes for common-specific models (there are none).
- User, Group, Token admin registrations live in apps/user/admin.py.
"""

from django.contrib import admin


# ---------------------------------------------------------------------------
# Admin site branding
# ---------------------------------------------------------------------------
admin.site.site_header  = 'StallManagement Administration'
admin.site.site_title   = 'StallManagement Admin'
admin.site.index_title  = 'StallManagement — System Control Panel'


# ---------------------------------------------------------------------------
# Extend here if a shared/common model is ever added
# ---------------------------------------------------------------------------
# Example (do NOT add actual models to common — use the relevant app instead):
#
# from some_app.models import SomeSharedModel
#
# @admin.register(SomeSharedModel)
# class SomeSharedModelAdmin(admin.ModelAdmin):
#     list_display = ('id', 'name', 'create_time')
#     search_fields = ('name',)
#     ordering = ('-create_time',)
