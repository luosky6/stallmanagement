"""
api/stall/urls.py
=================
Includes the stall app's URL patterns under /api/stalls/.
"""

from django.urls import path, include

urlpatterns = [
    path('stalls/', include('apps.stall.urls', namespace='stall')),
]