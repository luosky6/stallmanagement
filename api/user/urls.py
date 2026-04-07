"""
api/user/urls.py
================
Includes the user app's URL patterns under /api/users/.
"""

from django.urls import path, include

urlpatterns = [
    path('users/', include('apps.user.urls', namespace='user')),
]