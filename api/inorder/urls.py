"""
api/inorder/urls.py
===================
Includes the inbound order app's URL patterns under /api/inorders/.
"""

from django.urls import path, include

urlpatterns = [
    path('inorders/', include('apps.inorder.urls', namespace='inorder')),
]