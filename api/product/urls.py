"""
api/product/urls.py
===================
Includes the product app's URL patterns under /api/products/.
"""

from django.urls import path, include

urlpatterns = [
    path('products/', include('apps.product.urls', namespace='product')),
]