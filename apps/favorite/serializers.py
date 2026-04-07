"""
apps/favorite/serializers.py
============================
DRF serializers for the Favorite model.

Serializers
-----------
FavoriteReadSerializer
    Full read-only representation returned by the list endpoint.
    Nests a compact product summary (id, sn, name, price, stock,
    category name) so the Vue favourites panel can render each item
    without a second request per product.
    Includes the is_low_stock and stock_status fields so the
    favourites list can show the same stock-level badges as the
    main inventory view.

FavoriteProductSerializer
    Compact product representation nested inside FavoriteReadSerializer.
    Slightly richer than ProductSummarySerializer — includes category
    name and stock status fields needed specifically for the favourites
    panel rendering.
"""

from rest_framework import serializers

from .models import Favorite
from apps.product.models import LOW_STOCK_THRESHOLD


# ---------------------------------------------------------------------------
# Nested product representation for the favourites panel
# ---------------------------------------------------------------------------
class FavoriteProductSerializer(serializers.Serializer):
    """
    Compact product snapshot embedded in every favourite response.

    Fields mirror what the Vue frontend's favourites panel renders:
    - id, sn, name, price      → product identity and price tag
    - stock, is_low_stock       → stock badge (green / orange / red)
    - stock_status              → 'ok' | 'low' | 'out'
    - category_name             → category pill label
    - description               → tooltip / detail view
    """

    id            = serializers.IntegerField(read_only=True)
    sn            = serializers.CharField(read_only=True)
    name          = serializers.CharField(read_only=True)
    price         = serializers.DecimalField(
        max_digits=10, decimal_places=2, read_only=True
    )
    stock         = serializers.IntegerField(read_only=True)
    description   = serializers.CharField(read_only=True)
    category_name = serializers.SerializerMethodField(read_only=True)
    is_low_stock  = serializers.BooleanField(read_only=True)
    is_out_of_stock = serializers.BooleanField(read_only=True)
    stock_status  = serializers.SerializerMethodField(read_only=True)

    def get_category_name(self, obj):
        """Return the category name string for the filter pill."""
        return obj.category.name if obj.category_id else None

    def get_stock_status(self, obj):
        """Return 'out' | 'low' | 'ok' matching ProductReadSerializer."""
        if obj.stock == 0:
            return 'out'
        if obj.stock < LOW_STOCK_THRESHOLD:
            return 'low'
        return 'ok'


# ---------------------------------------------------------------------------
# FavoriteReadSerializer — full read output
# ---------------------------------------------------------------------------
class FavoriteReadSerializer(serializers.ModelSerializer):
    """
    Read-only serializer returned by GET /api/favorites/.

    Each favourite entry includes:
    - id              → favourite record ID (used for direct delete)
    - product         → nested FavoriteProductSerializer (full product snapshot)
    - is_favourite    → always True (useful when this is embedded in product lists)
    - create_time     → when the user favourited this product
    """

    product      = FavoriteProductSerializer(read_only=True)
    is_favourite = serializers.SerializerMethodField(
        help_text='Always True in this context — this is a favourite record.',
    )

    class Meta:
        model  = Favorite
        fields = [
            'id',
            'product',
            'is_favourite',
            'create_time',
        ]
        read_only_fields = fields

    def get_is_favourite(self, _obj):
        """Constant True — every record in this serializer IS a favourite."""
        return True


# ---------------------------------------------------------------------------
# FavoriteToggleResponseSerializer — response shape for toggle endpoint
# ---------------------------------------------------------------------------
class FavoriteToggleResponseSerializer(serializers.Serializer):
    """
    Response body for POST /api/favorites/toggle/<product_id>/.

    Fields
    ------
    action          'added' | 'removed'
    is_favourite    True  (added) | False  (removed)
    product_id      The product that was toggled
    favorite_id     The new Favorite record id (present only when action='added')
    """

    action       = serializers.CharField(read_only=True)
    is_favourite = serializers.BooleanField(read_only=True)
    product_id   = serializers.IntegerField(read_only=True)
    favorite_id  = serializers.IntegerField(
        read_only=True,
        allow_null=True,
        help_text='ID of the created Favorite record; null when removed.',
    )
