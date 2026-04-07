"""
apps/customer/models.py
=======================
Customer model — maps to the `customer` table in db_market.sql.

IMPORTANT DISTINCTION
---------------------
This model represents EXTERNAL business contacts used in purchase and
sales orders:
  - Suppliers  (customer_type='supplier') → appear as the supplier field
                in inbound orders (inorder.customer_id)
  - Buyers     (customer_type='buyer')    → appear as the buyer field
                in outbound orders (outorder.customer_id)

This is COMPLETELY SEPARATE from apps.user.models.User, which represents
system accounts (people who log in to the application).
A buyer in this table is NOT the same as a user with role='customer'.

Database table: `customer`  (matches db_market.sql exactly)

SQL reference:
    CREATE TABLE `customer` (
      `id`            INT AUTO_INCREMENT PRIMARY KEY,
      `name`          VARCHAR(50) NOT NULL,
      `phone`         VARCHAR(20) NOT NULL,
      `address`       VARCHAR(128) NOT NULL,
      `customer_type` ENUM('supplier','buyer') DEFAULT 'buyer',
      `create_time`   DATETIME DEFAULT CURRENT_TIMESTAMP,
      `modify_time`   DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
    )
"""

from django.db import models
from django.core.validators import RegexValidator

from apps.common.mixins import TimeStampMixin


class Customer(TimeStampMixin):
    """
    External business contact — either a supplier or a buyer.

    Inherits from TimeStampMixin:
        create_time  →  auto-set on first save
        modify_time  →  auto-updated on every save

    No soft-delete mixin here: the db_market.sql `customer` table has no
    is_deleted column, so hard deletes are used.  Orders that reference a
    deleted customer are protected by ON DELETE CASCADE in the DB, but the
    DRF views below enforce a check before allowing deletion if related
    orders exist.
    """

    # ------------------------------------------------------------------
    # Customer type choices — mirror the ENUM in db_market.sql
    # ------------------------------------------------------------------
    class CustomerType(models.TextChoices):
        SUPPLIER = 'supplier', 'Supplier'
        BUYER    = 'buyer',    'Buyer'

    # ------------------------------------------------------------------
    # Phone number validator
    # Accepts formats commonly used in Singapore / international:
    #   +6591234567  |  6591234567  |  91234567  |  +1-800-555-0100
    # ------------------------------------------------------------------
    phone_validator = RegexValidator(
        regex   = r'^\+?[\d\s\-]{7,20}$',
        message = 'Enter a valid phone number (7–20 digits, optional +, spaces, or hyphens).',
    )

    # ------------------------------------------------------------------
    # Fields
    # ------------------------------------------------------------------
    name = models.CharField(
        max_length=50,
        verbose_name='Contact Name',
        help_text='Full name of the supplier or buyer.',
    )

    phone = models.CharField(
        max_length=20,
        validators=[phone_validator],
        verbose_name='Phone Number',
        help_text='Contact phone number.',
    )

    address = models.CharField(
        max_length=128,
        verbose_name='Address',
        help_text='Business address of the contact.',
    )

    customer_type = models.CharField(
        max_length=10,
        choices=CustomerType.choices,
        default=CustomerType.BUYER,
        verbose_name='Contact Type',
        help_text=(
            'supplier — provides goods for inbound orders.\n'
            'buyer    — purchases goods via outbound orders.'
        ),
    )

    # create_time, modify_time → inherited from TimeStampMixin

    # ------------------------------------------------------------------
    # Meta
    # ------------------------------------------------------------------
    class Meta:
        db_table            = 'customer'   # exact table name from db_market.sql
        verbose_name        = 'Customer'
        verbose_name_plural = 'Customers'
        ordering            = ['customer_type', 'name']

    # ------------------------------------------------------------------
    # String representation
    # ------------------------------------------------------------------
    def __str__(self):
        return f'{self.name} ({self.get_customer_type_display()})'

    # ------------------------------------------------------------------
    # Helper properties
    # ------------------------------------------------------------------
    @property
    def is_supplier(self):
        """True when this contact is a supplier (used in inbound orders)."""
        return self.customer_type == self.CustomerType.SUPPLIER

    @property
    def is_buyer(self):
        """True when this contact is a buyer (used in outbound orders)."""
        return self.customer_type == self.CustomerType.BUYER

    @property
    def has_inbound_orders(self):
        """True if this supplier has any linked inbound orders."""
        return self.inorder_set.exists()

    @property
    def has_outbound_orders(self):
        """True if this buyer has any linked outbound orders."""
        return self.outorder_set.exists()

    @property
    def has_any_orders(self):
        """True if this contact is referenced by any order (in or out)."""
        return self.has_inbound_orders or self.has_outbound_orders
