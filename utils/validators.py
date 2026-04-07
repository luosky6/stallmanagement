"""
utils/validators.py
===================
Shared input validators for the StallManagement project.

These validators are reusable across models, serializers, and forms.
They raise either:
  - django.core.exceptions.ValidationError  (for model/form validation)
  - rest_framework.serializers.ValidationError  (for DRF serializers,
    when called from a serializer's validate_* method)

Usage in a DRF serializer field:
    from utils.validators import validate_positive_integer
    amount = serializers.IntegerField(validators=[validate_positive_integer])

Usage in a serializer validate_* method:
    def validate_amount(self, value):
        validate_stock_quantity(value)   # raises ValidationError on failure
        return value

Usage in a Django model field:
    from utils.validators import validate_positive_integer
    amount = models.IntegerField(validators=[validate_positive_integer])
"""

import re
from decimal import Decimal

from django.core.exceptions import ValidationError


# ---------------------------------------------------------------------------
# Numeric validators
# ---------------------------------------------------------------------------
def validate_positive_integer(value, field_name: str = 'This field'):
    """
    Raises ValidationError if `value` is not a positive integer (> 0).

    Used for: order line amounts, stock quantities that must be non-zero.
    """
    try:
        value = int(value)
    except (TypeError, ValueError):
        raise ValidationError(f'{field_name} must be an integer.')
    if value <= 0:
        raise ValidationError(f'{field_name} must be greater than 0. Got {value}.')


def validate_non_negative_integer(value, field_name: str = 'This field'):
    """
    Raises ValidationError if `value` is a negative integer (< 0).

    Used for: initial stock on product creation (0 is a valid starting stock).
    """
    try:
        value = int(value)
    except (TypeError, ValueError):
        raise ValidationError(f'{field_name} must be an integer.')
    if value < 0:
        raise ValidationError(f'{field_name} cannot be negative. Got {value}.')


def validate_non_negative_decimal(value, field_name: str = 'This field'):
    """
    Raises ValidationError if `value` is a negative decimal.

    Used for: price and unit_price fields.
    """
    try:
        value = Decimal(str(value))
    except Exception:
        raise ValidationError(f'{field_name} must be a valid number.')
    if value < Decimal('0.00'):
        raise ValidationError(
            f'{field_name} cannot be negative. Got {value}.'
        )


def validate_price(value):
    """
    Raises ValidationError if price is negative or has more than 2 decimal places.

    Used for: Product.price, InOrderProduct.unit_price, OutOrderProduct.unit_price.
    """
    validate_non_negative_decimal(value, field_name='Price')
    try:
        d = Decimal(str(value))
        if d.as_tuple().exponent < -2:
            raise ValidationError(
                f'Price cannot have more than 2 decimal places. Got {value}.'
            )
    except ValidationError:
        raise
    except Exception:
        raise ValidationError('Price must be a valid decimal number.')


# ---------------------------------------------------------------------------
# String / text validators
# ---------------------------------------------------------------------------
def validate_non_blank_string(value, field_name: str = 'This field', max_length: int = None):
    """
    Raises ValidationError if `value` is blank (empty or whitespace-only).
    Optionally enforces a maximum length.

    Used for: name fields, order codes, product SN codes.
    """
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f'{field_name} cannot be blank.')
    if max_length and len(value.strip()) > max_length:
        raise ValidationError(
            f'{field_name} cannot exceed {max_length} characters. '
            f'Got {len(value.strip())}.'
        )


def validate_order_code_format(value: str, prefix: str = None):
    """
    Validates that an order code matches the expected format:
        {PREFIX}{YYYYMMDD}{sequence}

    Examples:
        IN2024112701   → valid inbound order code
        OUT2024112701  → valid outbound order code

    Parameters
    ----------
    value  : str   The order code to validate.
    prefix : str   Optional expected prefix ('IN' or 'OUT').
                   If None, any uppercase letters prefix is accepted.

    Raises ValidationError on invalid format.
    """
    value = value.strip().upper()

    if not value:
        raise ValidationError('Order code cannot be blank.')

    # Build the regex based on whether a prefix is required
    if prefix:
        pattern = rf'^{re.escape(prefix.upper())}\d{{8}}\d{{2,}}$'
    else:
        pattern = r'^[A-Z]+\d{8}\d{2,}$'

    if not re.match(pattern, value):
        expected = f'{prefix.upper() if prefix else "PREFIX"}YYYYMMDD<seq>'
        raise ValidationError(
            f'Order code "{value}" does not match the expected format '
            f'{expected} (e.g. IN20241201001).'
        )


def validate_product_sn_format(value: str):
    """
    Validates that a product SN (stock number) follows the project convention:
        {CATEGORY_CODE}-{3-digit number}

    Examples:
        CLT-001  ELEC-002  FOOD-003  HOME-001  BOOK-001

    Raises ValidationError if the format does not match.
    """
    value = value.strip().upper()
    pattern = r'^[A-Z]{2,8}-\d{3,6}$'
    if not re.match(pattern, value):
        raise ValidationError(
            f'Product SN "{value}" does not match the expected format '
            'CATEGORY-NNN (e.g. CLT-001, ELEC-002).'
        )


def validate_phone_number(value: str):
    """
    Validates a phone number for Singapore / international format.
    Accepts: +6591234567  |  91234567  |  +1-800-555-0100  |  (65) 9123 4567

    Raises ValidationError if the format is invalid.
    """
    value = value.strip()
    pattern = r'^\+?[\d\s\-().]{7,25}$'
    if not re.match(pattern, value):
        raise ValidationError(
            f'"{value}" is not a valid phone number. '
            'Enter 7–25 characters using digits, spaces, +, -, (, or ).'
        )


# ---------------------------------------------------------------------------
# Uniqueness validators (for use in serializer validate_* methods)
# ---------------------------------------------------------------------------
def validate_unique_order_code(code: str, model, exclude_pk=None):
    """
    Raises ValidationError if an order with the given code already exists.

    Parameters
    ----------
    code       : str   The order code to check.
    model      : Model class  (InOrder or OutOrder)
    exclude_pk : int | None   PK to exclude (for updates — skip the current record)
    """
    qs = model.objects.filter(code=code)
    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)
    if qs.exists():
        raise ValidationError(
            f'An order with code "{code}" already exists.'
        )


def validate_unique_product_sn(sn: str, exclude_pk=None):
    """
    Raises ValidationError if a product with the given SN already exists.

    Parameters
    ----------
    sn         : str   The product SN to check.
    exclude_pk : int | None   PK to exclude (for updates)
    """
    from apps.product.models import Product
    qs = Product.objects.filter(sn=sn)
    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)
    if qs.exists():
        raise ValidationError(
            f'A product with SN "{sn}" already exists.'
        )


def validate_unique_username(username: str, exclude_pk=None):
    """
    Raises ValidationError if a user with the given username already exists.

    Parameters
    ----------
    username   : str   The username to check (compared case-insensitively).
    exclude_pk : int | None   PK to exclude (for updates)
    """
    from apps.user.models import User
    qs = User.objects.filter(username__iexact=username)
    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)
    if qs.exists():
        raise ValidationError(
            f'The username "{username}" is already taken.'
        )


# ---------------------------------------------------------------------------
# Business-rule validators
# ---------------------------------------------------------------------------
def validate_stock_sufficient(product, requested_qty: int):
    """
    Raises InsufficientStockError if the product does not have enough stock.

    Parameters
    ----------
    product       : Product instance (with current .stock value)
    requested_qty : int  The quantity requested in the order line

    This is a lightweight pre-check validator.  The authoritative check
    that uses select_for_update() is performed inside transaction.atomic()
    in the outbound order view.  Both exist for defence in depth.
    """
    from .exceptions import InsufficientStockError
    if product.stock < requested_qty:
        raise InsufficientStockError(
            f'Insufficient stock for "{product.name}" [{product.sn}]. '
            f'Available: {product.stock}. Requested: {requested_qty}.',
            details={
                'product_id':   product.id,
                'product_sn':   product.sn,
                'product_name': product.name,
                'stock':        product.stock,
                'requested':    requested_qty,
                'shortfall':    requested_qty - product.stock,
            },
        )


def validate_supplier(customer):
    """
    Raises ValidationError if the given Customer is not a supplier.
    Used in inbound order creation to enforce the buyer/supplier distinction.
    """
    from apps.customer.models import Customer
    if customer.customer_type != Customer.CustomerType.SUPPLIER:
        raise ValidationError(
            f'Customer "{customer.name}" is a {customer.customer_type}, not a supplier. '
            'Inbound orders must reference a supplier.'
        )


def validate_buyer(customer):
    """
    Raises ValidationError if the given Customer is not a buyer.
    Used in outbound order creation to enforce the buyer/supplier distinction.
    """
    from apps.customer.models import Customer
    if customer.customer_type != Customer.CustomerType.BUYER:
        raise ValidationError(
            f'Customer "{customer.name}" is a {customer.customer_type}, not a buyer. '
            'Outbound orders must reference a buyer.'
        )


def validate_order_lines_not_empty(lines: list):
    """
    Raises ValidationError if the lines list is empty.
    Orders must have at least one product line.
    """
    if not lines:
        raise ValidationError(
            'At least one product line is required. '
            'An order cannot be created without any products.'
        )


def validate_no_duplicate_products_in_lines(lines: list):
    """
    Raises ValidationError if the same product_id appears more than once
    in the order lines list.

    Parameters
    ----------
    lines : list of dicts, each with a 'product_id' key.
    """
    product_ids = [line['product_id'] for line in lines]
    duplicates  = list(set(
        pid for pid in product_ids if product_ids.count(pid) > 1
    ))
    if duplicates:
        raise ValidationError(
            f'Duplicate product IDs in order lines: {duplicates}. '
            'Each product may appear only once per order — '
            'combine quantities into a single line item.'
        )
