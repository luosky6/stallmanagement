"""
apps/inorder/serializers.py
============================
DRF serializers for the InOrder and InOrderProduct models.

Serializers
-----------
InOrderProductReadSerializer
    Read-only line-item representation. Nests a compact product summary
    (id, sn, name, price, stock) and includes line_total.

InOrderProductWriteSerializer
    Write serializer for a single line item within the order write flow.
    Accepts product_id, amount, unit_price.

InOrderReadSerializer
    Full read-only order header with nested lines list.
    Includes computed totals: total_amount, total_value.

InOrderCreateSerializer
    Write serializer for POST /api/inorders/.
    Accepts the full order (header + lines) in one payload.
    Validates:
      - Code uniqueness
      - Supplier exists and is type='supplier'
      - At least one line
      - No duplicate product IDs within the same order
      - Amount ≥ 1 and unit_price ≥ 0 for every line

InOrderUpdateSerializer
    Write serializer for PATCH /api/inorders/<id>/.
    Only allowed on draft orders (immutability enforced in the view).
    Can update header fields (remark, status) and replace the lines list.
    Status transition rules are enforced in the view, not here.
"""

from decimal import Decimal

from rest_framework import serializers

from .models import InOrder, InOrderProduct
from apps.product.serializers import ProductSummarySerializer
from apps.customer.models import Customer
from apps.customer.serializers import CustomerReadSerializer


# ---------------------------------------------------------------------------
# 1. InOrderProductReadSerializer — line item read output
# ---------------------------------------------------------------------------
class InOrderProductReadSerializer(serializers.ModelSerializer):
    """Read-only line-item with nested product summary and computed line_total."""

    product    = ProductSummarySerializer(read_only=True)
    line_total = serializers.DecimalField(
        max_digits=12, decimal_places=2,
        read_only=True,
        source='line_total',
    )

    class Meta:
        model  = InOrderProduct
        fields = ['id', 'product', 'amount', 'unit_price', 'line_total']
        read_only_fields = fields


# ---------------------------------------------------------------------------
# 2. InOrderProductWriteSerializer — line item write input
# ---------------------------------------------------------------------------
class InOrderProductWriteSerializer(serializers.Serializer):
    """
    Validates a single line item within an order write payload.
    Used as a nested list inside InOrderCreateSerializer and
    InOrderUpdateSerializer.
    Not a ModelSerializer because line items are created/deleted in bulk
    inside the view's transaction.atomic() block, not individually.
    """

    product_id = serializers.IntegerField(
        min_value=1,
        help_text='ID of an existing product.',
    )
    amount = serializers.IntegerField(
        min_value=1,
        help_text='Quantity to purchase (must be ≥ 1).',
    )
    unit_price = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        required=False,
        allow_null=True,
        min_value=Decimal('0.00'),
        help_text='Purchase price per unit paid to the supplier (optional).',
    )

    def validate_product_id(self, value):
        from apps.product.models import Product
        if not Product.objects.filter(pk=value).exists():
            raise serializers.ValidationError(
                f'Product with id={value} does not exist.'
            )
        return value


# ---------------------------------------------------------------------------
# 3. InOrderReadSerializer — full order read output
# ---------------------------------------------------------------------------
class InOrderReadSerializer(serializers.ModelSerializer):
    """
    Read-only order header with nested supplier, operator summary, and lines.
    """

    customer       = CustomerReadSerializer(read_only=True)
    operator_name  = serializers.CharField(source='operator.name',     read_only=True)
    operator_username = serializers.CharField(source='operator.username', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    is_editable    = serializers.BooleanField(read_only=True)
    lines          = InOrderProductReadSerializer(many=True, read_only=True)
    total_amount   = serializers.IntegerField(read_only=True, source='total_amount')
    total_value    = serializers.DecimalField(
        max_digits=14, decimal_places=2,
        read_only=True, source='total_value',
    )

    class Meta:
        model  = InOrder
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
# 4. InOrderCreateSerializer — create a new order (POST)
# ---------------------------------------------------------------------------
class InOrderCreateSerializer(serializers.Serializer):
    """
    Write serializer for creating a new inbound order in a single request.

    Payload shape:
    {
        "code":        "IN2024120101",
        "customer_id": 1,
        "remark":      "Optional note",
        "lines": [
            { "product_id": 1, "amount": 50, "unit_price": 50.00 },
            { "product_id": 5, "amount": 30, "unit_price": 250.00 }
        ]
    }
    """

    code = serializers.CharField(
        max_length=50,
        help_text='Unique inbound order code.',
    )
    customer_id = serializers.IntegerField(
        help_text='ID of a Customer with type=supplier.',
    )
    remark = serializers.CharField(
        max_length=255,
        required=False,
        allow_blank=True,
        default='',
        help_text='Optional order notes.',
    )
    lines = InOrderProductWriteSerializer(
        many=True,
        help_text='At least one line item is required.',
    )

    # ── Field-level validation ──────────────────────────────────────────
    def validate_code(self, value):
        value = value.strip().upper()
        if not value:
            raise serializers.ValidationError('Order code cannot be blank.')
        if InOrder.objects.filter(code=value).exists():
            raise serializers.ValidationError(
                f'Inbound order with code "{value}" already exists.'
            )
        return value

    def validate_customer_id(self, value):
        try:
            supplier = Customer.objects.get(pk=value)
        except Customer.DoesNotExist:
            raise serializers.ValidationError(
                f'Customer with id={value} does not exist.'
            )
        if supplier.customer_type != Customer.CustomerType.SUPPLIER:
            raise serializers.ValidationError(
                f'Customer "{supplier.name}" is a buyer, not a supplier. '
                'Inbound orders require a supplier.'
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
            duplicates = [pid for pid in product_ids if product_ids.count(pid) > 1]
            raise serializers.ValidationError({
                'lines': (
                    f'Duplicate product IDs found: {list(set(duplicates))}. '
                    'Each product may appear only once per order. '
                    'Combine quantities into a single line item.'
                )
            })

        return attrs


# ---------------------------------------------------------------------------
# 5. InOrderUpdateSerializer — update a draft order (PATCH)
# ---------------------------------------------------------------------------
class InOrderUpdateSerializer(serializers.Serializer):
    """
    Write serializer for updating a draft inbound order.

    All fields are optional (PATCH semantics).
    If 'lines' is provided, the ENTIRE lines list is replaced (not merged).
    Status changes are handled here but transition rules are validated in
    the view before this serializer is called.

    Immutability note
    -----------------
    'code' and 'customer_id' are intentionally excluded — order code and
    supplier cannot be changed after creation (business rule).
    """

    status = serializers.ChoiceField(
        choices=InOrder.Status.choices,
        required=False,
        help_text='draft | completed | cancelled',
    )
    remark = serializers.CharField(
        max_length=255,
        required=False,
        allow_blank=True,
        help_text='Updated order notes.',
    )
    lines = InOrderProductWriteSerializer(
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
                'Include at least one line item, or omit lines to keep the current ones.'
            )
        if lines:
            product_ids = [line['product_id'] for line in lines]
            if len(product_ids) != len(set(product_ids)):
                duplicates = [pid for pid in product_ids if product_ids.count(pid) > 1]
                raise serializers.ValidationError(
                    f'Duplicate product IDs: {list(set(duplicates))}. '
                    'Combine quantities into a single line item.'
                )
        return lines
