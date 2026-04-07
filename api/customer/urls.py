"""
api/customer/urls.py
====================
Includes the customer app's URL patterns under /api/customers/.
"""

from django.urls import path, include

urlpatterns = [
    path('customers/', include('apps.customer.urls', namespace='customer')),
]