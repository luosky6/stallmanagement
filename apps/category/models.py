"""
apps/category/models.py
=======================
Category model — maps to the `categories` table in db_market.sql.

Role in the system
------------------
Every product must belong to exactly one category (FK with RESTRICT on
delete, meaning a category cannot be removed while it still has products
assigned to it).

The frontend uses categories in two ways:
  1. As a filter pill row on the Inventory tab (All / Clothing / Electronics /
     Food & Beverages / Home Essentials / Books & Media / Other)
  2. As a dropdown on the Add/Edit Product form

Database table: `categories`  (matches db_market.sql exactly)

SQL reference:
    CREATE TABLE `categories` (
      `id`          INT AUTO_INCREMENT PRIMARY KEY,
      `name`        VARCHAR(50) NOT NULL UNIQUE,
      `description` VARCHAR(255),
      `create_time` DATETIME DEFAULT CURRENT_TIMESTAMP,
      `modify_time` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
    )

Seed data (from db_market.sql INSERT):
    Clothing | Electronics | Food & Beverages |
    Home Essentials | Books & Media | Other
"""

from django.db import models
from apps.common.mixins import TimeStampMixin


class Category(TimeStampMixin):
    """
    Product category.

    Inherits from TimeStampMixin:
        create_time  →  auto-set on first save
        modify_time  →  auto-updated on every save

    No soft-delete: the `categories` table has no is_deleted column.
    Deletion is guarded in the view layer — a category with assigned
    products cannot be deleted (mirrors the DB-level ON DELETE RESTRICT
    on the products.category_id foreign key).
    """

    name = models.CharField(
        max_length=50,
        unique=True,
        verbose_name='Category Name',
        help_text='Unique display name shown as a filter pill in the inventory view.',
        error_messages={
            'unique': 'A category with this name already exists.',
        },
    )

    description = models.CharField(
        max_length=255,
        blank=True,
        default='',
        verbose_name='Description',
        help_text='Optional short description of what products belong to this category.',
    )

    # create_time, modify_time → inherited from TimeStampMixin

    # ------------------------------------------------------------------
    # Meta
    # ------------------------------------------------------------------
    class Meta:
        db_table            = 'categories'   # exact table name from db_market.sql
        verbose_name        = 'Category'
        verbose_name_plural = 'Categories'
        ordering            = ['name']

    # ------------------------------------------------------------------
    # String representation
    # ------------------------------------------------------------------
    def __str__(self):
        return self.name

    # ------------------------------------------------------------------
    # Helper properties
    # ------------------------------------------------------------------
    @property
    def product_count(self):
        """Number of products currently assigned to this category."""
        return self.product_set.count()

    @property
    def has_products(self):
        """
        True if at least one product belongs to this category.
        Used by the delete guard to mirror ON DELETE RESTRICT behaviour
        at the application layer before it hits the DB constraint.
        """
        return self.product_set.exists()
