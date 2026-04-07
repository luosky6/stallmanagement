"""
api/outorder/urls.py
====================
Includes the outbound order app's URL patterns under /api/outorders/.
"""

from django.urls import path, include

urlpatterns = [
    path('outorders/', include('apps.outorder.urls', namespace='outorder')),
]