"""
api/filters.py
==============
Global django-filter FilterSet classes for the StallManagement project.

These FilterSets are registered in settings.py via:
    REST_FRAMEWORK = {
        'DEFAULT_FILTER_BACKENDS': [
            'django_filters.rest_framework.DjangoFilterBackend',
            'rest_framework.filters.SearchFilter',
            'rest_framework.filters.OrderingFilter',
        ],
    }

Each FilterSet maps URL query parameters to ORM filter expressions.
They are used directly by the api/* sub-package views when passed as
filterset_class on a ViewSet, or accessed manually in APIView.get().

FilterSets
----------
ProductFilter       /api/products/      category_id, stock_status, price range
InOrderFilter       /api/inorders/      status, customer_id, date range
OutOrderFilter      /api/outorders/     status, customer_id, date range
ChatMessageFilter   /api/chat/history/  is_read, date range
UserFilter          /api/users/         role, is_active
CustomerFilter      /api/customers/     customer_type
"""

import django_filters

from apps.product.models import Product, LOW_STOCK_THRESHOLD
from apps.inorder.models import InOrder
from apps.outorder.models import OutOrder
from apps.chat.models import ChatMessage
from apps.user.models import User
from apps.customer.models import Customer


# ---------------------------------------------------------------------------
# ProductFilter
# ---------------------------------------------------------------------------
class ProductFilter(django_filters.FilterSet):
    """
    Filter products by category, stock status, and price range.

    Query parameters:
        category_id     exact FK match
        stock_status    'ok' | 'low' | 'out'  (custom method filter)
        price_min       price ≥ value
        price_max       price ≤ value
        search          name / sn / description contains (SearchFilter handles this)
    """

    category_id  = django_filters.NumberFilter(
        field_name='category_id',
        lookup_expr='exact',
        label='Category ID',
    )
    price_min = django_filters.NumberFilter(
        field_name='price',
        lookup_expr='gte',
        label='Minimum price (inclusive)',
    )
    price_max = django_filters.NumberFilter(
        field_name='price',
        lookup_expr='lte',
        label='Maximum price (inclusive)',
    )
    stock_status = django_filters.CharFilter(
        method='filter_stock_status',
        label="Stock status: 'ok' | 'low' | 'out'",
    )

    class Meta:
        model  = Product
        fields = ['category_id', 'price_min', 'price_max', 'stock_status']

    def filter_stock_status(self, queryset, name, value):
        value = value.strip().lower()
        if value == 'out':
            return queryset.filter(stock=0)
        if value == 'low':
            return queryset.filter(stock__gt=0, stock__lt=LOW_STOCK_THRESHOLD)
        if value == 'ok':
            return queryset.filter(stock__gte=LOW_STOCK_THRESHOLD)
        return queryset   # unknown value → no filter applied


# ---------------------------------------------------------------------------
# InOrderFilter
# ---------------------------------------------------------------------------
class InOrderFilter(django_filters.FilterSet):
    """
    Filter inbound orders by status, supplier, and date range.

    Query parameters:
        status          exact
        customer_id     exact FK match (supplier)
        date_from       create_time ≥ YYYY-MM-DD
        date_to         create_time ≤ YYYY-MM-DD
    """

    status      = django_filters.ChoiceFilter(choices=InOrder.Status.choices)
    customer_id = django_filters.NumberFilter(field_name='customer_id', lookup_expr='exact')
    date_from   = django_filters.DateFilter(field_name='create_time', lookup_expr='date__gte')
    date_to     = django_filters.DateFilter(field_name='create_time', lookup_expr='date__lte')

    class Meta:
        model  = InOrder
        fields = ['status', 'customer_id', 'date_from', 'date_to']


# ---------------------------------------------------------------------------
# OutOrderFilter
# ---------------------------------------------------------------------------
class OutOrderFilter(django_filters.FilterSet):
    """
    Filter outbound orders by status, buyer, and date range.

    Query parameters:
        status          exact
        customer_id     exact FK match (buyer)
        date_from       create_time ≥ YYYY-MM-DD
        date_to         create_time ≤ YYYY-MM-DD
    """

    status      = django_filters.ChoiceFilter(choices=OutOrder.Status.choices)
    customer_id = django_filters.NumberFilter(field_name='customer_id', lookup_expr='exact')
    date_from   = django_filters.DateFilter(field_name='create_time', lookup_expr='date__gte')
    date_to     = django_filters.DateFilter(field_name='create_time', lookup_expr='date__lte')

    class Meta:
        model  = OutOrder
        fields = ['status', 'customer_id', 'date_from', 'date_to']


# ---------------------------------------------------------------------------
# ChatMessageFilter
# ---------------------------------------------------------------------------
class ChatMessageFilter(django_filters.FilterSet):
    """
    Filter chat messages by read status and date range.

    Query parameters:
        is_read     true | false
        date_from   create_time ≥ YYYY-MM-DD
        date_to     create_time ≤ YYYY-MM-DD
    """

    is_read   = django_filters.BooleanFilter(field_name='is_read')
    date_from = django_filters.DateFilter(field_name='create_time', lookup_expr='date__gte')
    date_to   = django_filters.DateFilter(field_name='create_time', lookup_expr='date__lte')

    class Meta:
        model  = ChatMessage
        fields = ['is_read', 'date_from', 'date_to']


# ---------------------------------------------------------------------------
# UserFilter
# ---------------------------------------------------------------------------
class UserFilter(django_filters.FilterSet):
    """
    Filter users by role and active status.

    Query parameters:
        role        admin | stall_owner | customer
        is_active   true | false
    """

    role      = django_filters.ChoiceFilter(choices=User.Role.choices)
    is_active = django_filters.BooleanFilter(field_name='is_active')

    class Meta:
        model  = User
        fields = ['role', 'is_active']


# ---------------------------------------------------------------------------
# CustomerFilter
# ---------------------------------------------------------------------------
class CustomerFilter(django_filters.FilterSet):
    """
    Filter customers (contacts) by type.

    Query parameters:
        customer_type   supplier | buyer
    """

    customer_type = django_filters.ChoiceFilter(choices=Customer.CustomerType.choices)

    class Meta:
        model  = Customer
        fields = ['customer_type']