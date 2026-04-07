"""
apps/product/models.py
======================
Product model — maps to the `products` table in db_market.sql.

Role in the system
------------------
Products are the central entity of the stall management system:
  - Every inbound order line (inorder_products) references a product
    and increases its stock on completion.
  - Every outbound order line (outorder_products) references a product
    and decreases its stock on completion.
  - Customers can favourite products (favorites.product_id).
  - Products are filtered and displayed on the Inventory tab of the Vue
    SPA, grouped by category with stock-level colour coding.

Stock management note
---------------------
Stock adjustments are NEVER done by writing directly to this model
from view code.  They are always performed through the atomic helper
in utils/helpers.py (adjust_stock) which wraps the update in a
select_for_update() + transaction.atomic() to prevent race conditions
when two orders are processed simultaneously.

Database table: `products`  (matches db_market.sql exactly)

SQL reference:
    CREATE TABLE `products` (
      `id`          INT AUTO_INCREMENT PRIMARY KEY,
      `sn`          VARCHAR(50) NOT NULL UNIQUE,
      `name`        VARCHAR(100) NOT NULL,
      `price`       DECIMAL(10,2) NOT NULL,
      `category_id` INT NOT NULL REFERENCES categories(id) ON DELETE RESTRICT,
      `stock`       INT DEFAULT 0,
      `description` VARCHAR(255),
      `create_time` DATETIME DEFAULT CURRENT_TIMESTAMP,
      `modify_time` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
    )
"""

from django.db import models
from django.core.validators import MinValueValidator

from apps.common.mixins import TimeStampMixin


# Low-stock threshold used by the frontend to colour rows red
# (mirrors the frontend logic: tr.row-low when stock < LOW_STOCK_THRESHOLD)
LOW_STOCK_THRESHOLD = 20


class Product(TimeStampMixin):
    """
    A product sold or purchased through the stall.

    Inherits from TimeStampMixin:
        create_time  →  auto-set on first save
        modify_time  →  auto-updated on every save

    No soft-delete: the `products` table has no is_deleted column.
    Deletion is guarded at the view layer — a product referenced by
    any order line cannot be deleted (mirrors ON DELETE CASCADE on
    inorder_products / outorder_products, but we prefer to keep the
    order history intact rather than cascade-delete it).
    """

    # ------------------------------------------------------------------
    # Fields — every field maps directly to a column in db_market.sql
    # ------------------------------------------------------------------
    sn = models.CharField(
        max_length=50,
        unique=True,
        verbose_name='Product Code (SN)',
        help_text=(
            'Unique stock-keeping unit code. '
            'Format examples: CLT-001, ELEC-002, FOOD-003.'
        ),
        error_messages={
            'unique': 'A product with this SN already exists.',
        },
    )

    name = models.CharField(
        max_length=100,
        verbose_name='Product Name',
        help_text='Display name shown in the inventory table and order forms.',
    )

    price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name='Unit Price',
        help_text='Selling price per unit (must be ≥ 0).',
        validators=[
            MinValueValidator(
                limit_value=0,
                message='Price must be 0 or greater.',
            )
        ],
    )

    category = models.ForeignKey(
        'category.Category',
        on_delete=models.RESTRICT,      # mirrors ON DELETE RESTRICT in SQL
        verbose_name='Category',
        help_text='Product category — cannot be deleted while products are assigned.',
        db_column='category_id',        # keeps the FK column name as category_id
    )

    stock = models.IntegerField(
        default=0,
        verbose_name='Stock Quantity',
        help_text='Current on-hand quantity. Updated automatically by inbound/outbound orders.',
        validators=[
            MinValueValidator(
                limit_value=0,
                message='Stock cannot be negative.',
            )
        ],
    )

    description = models.CharField(
        max_length=255,
        blank=True,
        default='',
        verbose_name='Description',
        help_text='Short description shown in the product detail tooltip.',
    )

    # create_time, modify_time → inherited from TimeStampMixin

    # ------------------------------------------------------------------
    # Meta
    # ------------------------------------------------------------------
    class Meta:
        app_label = 'product'
        db_table            = 'products'   # exact table name from db_market.sql
        verbose_name        = 'Product'
        verbose_name_plural = 'Products'
        ordering            = ['category', 'name']
        indexes = [
            # Speed up the most common filter: products by category
            models.Index(fields=['category'], name='idx_product_category'),
            # Speed up SN lookup (already unique, but explicit index for clarity)
            models.Index(fields=['sn'],       name='idx_product_sn'),
            # Speed up low-stock alerts
            models.Index(fields=['stock'],    name='idx_product_stock'),
        ]

    # ------------------------------------------------------------------
    # String representation
    # ------------------------------------------------------------------
    def __str__(self):
        return f'[{self.sn}] {self.name}'

    # ------------------------------------------------------------------
    # Stock-level helper properties
    # ------------------------------------------------------------------
    @property
    def is_low_stock(self):
        """
        True when stock is below LOW_STOCK_THRESHOLD (20 units).
        Mirrors the frontend's  tr.row-low  CSS class condition.
        """
        return self.stock < LOW_STOCK_THRESHOLD

    @property
    def is_out_of_stock(self):
        """True when stock has reached zero — cannot be sold."""
        return self.stock == 0

    # ------------------------------------------------------------------
    # Order reference helpers (used by deletion guard in views)
    # ------------------------------------------------------------------
    @property
    def has_inbound_order_lines(self):
        """True if this product appears in any inbound order line."""
        return self.inorderproduct_set.exists()

    @property
    def has_outbound_order_lines(self):
        """True if this product appears in any outbound order line."""
        return self.outorderproduct_set.exists()

    @property
    def has_any_order_lines(self):
        """True if this product is referenced by any order line."""
        return self.has_inbound_order_lines or self.has_outbound_order_lines
