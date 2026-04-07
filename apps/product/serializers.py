"""
apps/product/serializers.py
============================
DRF serializers for the Product model.

Serializers
-----------
ProductReadSerializer
    Full read-only representation returned in list and retrieve responses.
    Nests a CategorySummarySerializer so the frontend receives category
    id + name without a second request.
    Adds computed fields: is_low_stock, is_out_of_stock, stock_status_label.

ProductWriteSerializer
    Shared write serializer used for both CREATE (POST) and UPDATE (PATCH).
    Validates sn uniqueness, price ≥ 0, stock ≥ 0, and that category_id
    refers to an existing category.

ProductSummarySerializer
    Lightweight (id, sn, name, price, stock) serializer used as a nested
    field inside InOrderProductSerializer and OutOrderProductSerializer
    so order line responses include enough product info without embedding
    the full product object.
"""

from decimal import Decimal

from rest_framework import serializers

from .models import Product, LOW_STOCK_THRESHOLD
from apps.category.serializers import CategorySummarySerializer
from apps.category.models import Category


# ---------------------------------------------------------------------------
# 1. ProductReadSerializer — full read output
# ---------------------------------------------------------------------------
class ProductReadSerializer(serializers.ModelSerializer):
    """
    Read-only serializer returned by list / retrieve endpoints.

    Nested fields
    -------------
    category        →  CategorySummarySerializer (id + name)
    is_low_stock    →  bool (stock < LOW_STOCK_THRESHOLD)
    is_out_of_stock →  bool (stock == 0)
    stock_status    →  'ok' | 'low' | 'out'  (for frontend badge colouring)
    """

    category = CategorySummarySerializer(read_only=True)

    is_low_stock    = serializers.BooleanField(read_only=True)
    is_out_of_stock = serializers.BooleanField(read_only=True)

    stock_status = serializers.SerializerMethodField(
        help_text="'out' if stock=0, 'low' if stock<threshold, else 'ok'.",
    )

    low_stock_threshold = serializers.SerializerMethodField(
        help_text='The threshold value below which stock is considered low.',
    )

    class Meta:
        model  = Product
        fields = [
            'id',
            'sn',
            'name',
            'price',
            'category',
            'stock',
            'description',
            'is_low_stock',
            'is_out_of_stock',
            'stock_status',
            'low_stock_threshold',
            'create_time',
            'modify_time',
        ]
        read_only_fields = fields

    def get_stock_status(self, obj):
        if obj.is_out_of_stock:
            return 'out'
        if obj.is_low_stock:
            return 'low'
        return 'ok'

    def get_low_stock_threshold(self, _obj):
        return LOW_STOCK_THRESHOLD


# ---------------------------------------------------------------------------
# 2. ProductWriteSerializer — create and update
# ---------------------------------------------------------------------------
class ProductWriteSerializer(serializers.ModelSerializer):
    """
    Write serializer for POST /api/products/ and PATCH /api/products/<id>/.

    Accepts category_id (integer FK) rather than a nested object.
    Returns the full ProductReadSerializer representation after save.

    Validation rules
    ----------------
    sn
        Required on create; optional on partial update.
        Stripped and uppercased.
        Must be unique (checked explicitly for a friendly error message).

    name
        Required. Stripped of whitespace.

    price
        Must be >= 0.00 (non-negative).
        Max 8 digits before decimal, 2 after (DECIMAL(10,2)).

    category_id
        Must reference an existing, non-deleted Category.

    stock
        Must be >= 0 (cannot create a product with negative stock).
        Defaults to 0 if omitted on create.

    description
        Optional. Stripped; stored as empty string if blank.
    """

    # Accept category_id as a plain integer write field
    category_id = serializers.IntegerField(
        help_text='ID of an existing Category record.',
    )

    class Meta:
        model  = Product
        fields = [
            'sn',
            'name',
            'price',
            'category_id',
            'stock',
            'description',
        ]
        extra_kwargs = {
            'sn':          {'help_text': 'Unique product code, e.g. CLT-001.'},
            'name':        {'help_text': 'Product display name.'},
            'price':       {'help_text': 'Selling price per unit (≥ 0).'},
            'stock':       {'required': False, 'default': 0,
                            'help_text': 'Initial stock quantity (≥ 0, default 0).'},
            'description': {'required': False, 'allow_blank': True, 'default': ''},
        }

    # ── Field-level validation ──────────────────────────────────────────
    def validate_sn(self, value):
        """Normalise to uppercase and verify uniqueness."""
        value = value.strip().upper()
        if not value:
            raise serializers.ValidationError('Product code (SN) cannot be blank.')

        qs = Product.objects.filter(sn=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError(
                f'Product with SN "{value}" already exists.'
            )
        return value

    def validate_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError('Product name cannot be blank.')
        return value

    def validate_price(self, value):
        if value < Decimal('0.00'):
            raise serializers.ValidationError('Price must be 0.00 or greater.')
        return value

    def validate_stock(self, value):
        if value < 0:
            raise serializers.ValidationError('Stock quantity cannot be negative.')
        return value

    def validate_category_id(self, value):
        """Verify the referenced category actually exists."""
        if not Category.objects.filter(pk=value).exists():
            raise serializers.ValidationError(
                f'Category with id={value} does not exist.'
            )
        return value

    def validate_description(self, value):
        return value.strip() if value else ''

    # ── Save ────────────────────────────────────────────────────────────
    def create(self, validated_data):
        return Product.objects.create(**validated_data)

    def update(self, instance, validated_data):
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        return instance


# ---------------------------------------------------------------------------
# 3. ProductSummarySerializer — lightweight nested use in order lines
# ---------------------------------------------------------------------------
class ProductSummarySerializer(serializers.ModelSerializer):
    """
    Minimal serializer embedded inside order-line serializers.

    Fields: id, sn, name, price, stock
    Provides just enough context for the order form dropdowns and
    the order detail table (stock is included so the frontend can
    validate available quantity without a separate request).
    """

    class Meta:
        model  = Product
        fields = ['id', 'sn', 'name', 'price', 'stock']
        read_only_fields = fields
