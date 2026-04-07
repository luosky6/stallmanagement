"""
api/favorite/urls.py
====================
Includes the favourite app's URL patterns under /api/favorites/.
"""

from django.urls import path, include

urlpatterns = [
    path('favorites/', include('apps.favorite.urls', namespace='favorite')),
]