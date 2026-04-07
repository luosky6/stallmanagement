"""
apps/outorder/serializers.py
=============================
DRF serializers for the OutOrder and OutOrderProduct models.

Serializers
-----------
OutOrderProductReadSerializer
    Read-only line-item representation. Nests ProductSummarySerializer
    and exposes line_total.

OutOrderProductWriteSerializer
    Write serializer for a single line item. Validates product_id exists,
    amount ≥ 1, and unit_price ≥ 0.

OutOrderReadSerializer
    Full read-only order header with nested lines, buyer, operator summary,
    and computed totals: total_amount, total_value.

OutOrderCreateSerializer
    Write serializer for POST /api/outorders/.
    Validates:
      - Code uniqueness
      - Buyer exists and is type='buyer' (not supplier)
      - At least one line item
      - No duplicate product_ids within the same order
      - Amount ≥ 1 and unit_price ≥ 0 for every line
    NOTE: Stock sufficiency is NOT checked here — it is checked inside
          transaction.atomic() in the view using select_for_update() to
          prevent race conditions with concurrent orders.

OutOrderUpdateSerializer
    Write serializer for PATCH /api/outorders/<id>/ (draft orders only).
    Excludes code and customer_id (immutable after creation).
    If lines are provided, the entire list is replaced.
"""

from decimal import Decimal

from rest_framework import serializers

from .models import OutOrder, OutOrderProduct
from apps.product.serializers import ProductSummarySerializer
from apps.customer.models import Customer
from apps.customer.serializers import CustomerReadSerializer


# ---------------------------------------------------------------------------
# 1. OutOrderProductReadSerializer — line item read output
# ---------------------------------------------------------------------------
class OutOrderProductReadSerializer(serializers.ModelSerializer):
    """Read-only line-item with nested product summary and computed line_total."""

    product    = ProductSummarySerializer(read_only=True)
    line_total = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        read_only=True,
        source='line_total',
    )

    class Meta:
        model  = OutOrderProduct
        fields = ['id', 'product', 'amount', 'unit_price', 'line_total']
        read_only_fields = fields


# ---------------------------------------------------------------------------
# 2. OutOrderProductWriteSerializer — line item write input
# ---------------------------------------------------------------------------
class OutOrderProductWriteSerializer(serializers.Serializer):
    """
    Validates a single line item within an outbound order write payload.
    Plain Serializer (not ModelSerializer) — lines are created in bulk
    inside transaction.atomic() in the view, not individually.
    """

    product_id = serializers.IntegerField(
        min_value=1,
        help_text='ID of an existing product.',
    )
    amount = serializers.IntegerField(
        min_value=1,
        help_text='Quantity to sell (must be ≥ 1).',
    )
    unit_price = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        required=False,
        allow_null=True,
        min_value=Decimal('0.00'),
        help_text='Selling price per unit charged to the buyer (optional).',
    )

    def validate_product_id(self, value):
        from apps.product.models import Product
        if not Product.objects.filter(pk=value).exists():
            raise serializers.ValidationError(
                f'Product with id={value} does not exist.'
            )
        return value


# ---------------------------------------------------------------------------
# 3. OutOrderReadSerializer — full order read output
# ---------------------------------------------------------------------------
class OutOrderReadSerializer(serializers.ModelSerializer):
    """
    Read-only order header with nested buyer, operator summary, and lines.
    Includes computed totals and editable/status flags.
    """

    customer          = CustomerReadSerializer(read_only=True)
    operator_name     = serializers.CharField(source='operator.name',     read_only=True)
    operator_username = serializers.CharField(source='operator.username', read_only=True)
    status_display    = serializers.CharField(source='get_status_display', read_only=True)
    is_editable       = serializers.BooleanField(read_only=True)
    lines             = OutOrderProductReadSerializer(many=True, read_only=True)
    total_amount      = serializers.IntegerField(read_only=True, source='total_amount')
    total_value       = serializers.DecimalField(
        max_digits=14,
        decimal_places=2,
        read_only=True,
        source='total_value',
    )

    class Meta:
        model  = OutOrder
        fields = [
            'id',
            'code',
            'customer',
            'operator_name',
            'operator_username',
            'status',
            'status_display',
            'is_editable',
            'remark',
            'lines',
            'total_amount',
            'total_value',
            'create_time',
            'modify_time',
        ]
        read_only_fields = fields


# ---------------------------------------------------------------------------
# 4. OutOrderCreateSerializer — create a new order (POST)
# ---------------------------------------------------------------------------
class OutOrderCreateSerializer(serializers.Serializer):
    """
    Write serializer for creating a new outbound order.

    Payload shape:
    {
        "code":        "OUT2024120101",
        "customer_id": 3,
        "remark":      "Optional note",
        "lines": [
            { "product_id": 1, "amount": 20, "unit_price": 59.99 },
            { "product_id": 2, "amount": 15, "unit_price": 129.99 }
        ]
    }

    Stock check is intentionally NOT performed here.
    It is performed inside transaction.atomic() in the view using
    select_for_update() to prevent TOCTOU race conditions.
    """

    code = serializers.CharField(
        max_length=50,
        help_text='Unique outbound order code.',
    )
    customer_id = serializers.IntegerField(
        help_text='ID of a Customer with type=buyer.',
    )
    remark = serializers.CharField(
        max_length=255,
        required=False,
        allow_blank=True,
        default='',
        help_text='Optional order notes.',
    )
    lines = OutOrderProductWriteSerializer(
        many=True,
        help_text='At least one line item is required.',
    )

    # ── Field-level validation ──────────────────────────────────────────
    def validate_code(self, value):
        value = value.strip().upper()
        if not value:
            raise serializers.ValidationError('Order code cannot be blank.')
        if OutOrder.objects.filter(code=value).exists():
            raise serializers.ValidationError(
                f'Outbound order with code "{value}" already exists.'
            )
        return value

    def validate_customer_id(self, value):
        try:
            buyer = Customer.objects.get(pk=value)
        except Customer.DoesNotExist:
            raise serializers.ValidationError(
                f'Customer with id={value} does not exist.'
            )
        if buyer.customer_type != Customer.CustomerType.BUYER:
            raise serializers.ValidationError(
                f'Customer "{buyer.name}" is a supplier, not a buyer. '
                'Outbound orders require a buyer.'
            )
        return value

    def validate_remark(self, value):
        return value.strip() if value else ''

    # ── Object-level validation ─────────────────────────────────────────
    def validate(self, attrs):
        lines = attrs.get('lines', [])

        if not lines:
            raise serializers.ValidationError(
                {'lines': 'At least one line item is required.'}
            )

        # Detect duplicate product_ids within the same order
        product_ids = [line['product_id'] for line in lines]
        if len(product_ids) != len(set(product_ids)):
            duplicates = list(set(
                pid for pid in product_ids if product_ids.count(pid) > 1
            ))
            raise serializers.ValidationError({
                'lines': (
                    f'Duplicate product IDs found: {duplicates}. '
                    'Each product may appear only once per order. '
                    'Combine quantities into a single line item.'
                )
            })

        return attrs


# ---------------------------------------------------------------------------
# 5. OutOrderUpdateSerializer — update a draft order (PATCH)
# ---------------------------------------------------------------------------
class OutOrderUpdateSerializer(serializers.Serializer):
    """
    Write serializer for PATCH /api/outorders/<id>/ (draft orders only).

    code and customer_id are excluded — immutable after creation.
    If lines are provided, the entire list is replaced.
    Status transitions use dedicated action endpoints, not this serializer.
    """

    remark = serializers.CharField(
        max_length=255,
        required=False,
        allow_blank=True,
        help_text='Updated order notes.',
    )
    lines = OutOrderProductWriteSerializer(
        many=True,
        required=False,
        help_text=(
            'If provided, completely replaces the existing lines. '
            'Omit to keep existing lines unchanged.'
        ),
    )

    def validate_remark(self, value):
        return value.strip() if value else ''

    def validate_lines(self, lines):
        if lines is not None and len(lines) == 0:
            raise serializers.ValidationError(
                'Lines list cannot be empty. '
                'Include at least one line item or omit lines to keep the current ones.'
            )
        if lines:
            product_ids = [line['product_id'] for line in lines]
            if len(product_ids) != len(set(product_ids)):
                duplicates = list(set(
                    pid for pid in product_ids if product_ids.count(pid) > 1
                ))
                raise serializers.ValidationError(
                    f'Duplicate product IDs: {duplicates}. '
                    'Combine quantities into a single line item.'
                )
        return lines
