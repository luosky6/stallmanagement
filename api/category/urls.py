"""
api/category/urls.py
====================
Includes the category app's URL patterns under /api/categories/.
"""

from django.urls import path, include

urlpatterns = [
    path('categories/', include('apps.category.urls', namespace='category')),
]