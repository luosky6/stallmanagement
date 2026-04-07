"""
apps/favorite/models.py
=======================
Favorite model — maps to the `favorites` table in db_market.sql.

Role in the system
------------------
Customers can bookmark products they are interested in purchasing.
The Vue frontend shows a star/heart toggle button next to every product
in the inventory view.  Clicking the button calls the toggle endpoint,
which adds the record if it does not exist or removes it if it does
(idempotent toggle semantics).

The favourites list is scoped to the authenticated user — each user can
only see and manage their own favourites.

Uniqueness
----------
The DB enforces a unique constraint on (user_id, product_id) so that a
user cannot favourite the same product twice.  The toggle view leverages
get_or_create / filter().delete() to implement atomic add/remove without
a separate check-then-act sequence.

No soft-delete: the `favorites` table has no is_deleted column.
Removing a favourite is a genuine hard delete of the row.

Database table: `favorites`  (matches db_market.sql exactly)

SQL reference:
    CREATE TABLE `favorites` (
      `id`         INT AUTO_INCREMENT PRIMARY KEY,
      `user_id`    INT NOT NULL REFERENCES users(id)    ON DELETE CASCADE,
      `product_id` INT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
      `create_time` DATETIME DEFAULT CURRENT_TIMESTAMP,
      UNIQUE KEY `unique_user_product` (`user_id`, `product_id`)
    )
"""

from django.conf import settings
from django.db import models

from apps.common.mixins import TimeStampMixin


class Favorite(TimeStampMixin):
    """
    A single favourite bookmark: one user → one product.

    Inherits from TimeStampMixin:
        create_time  →  auto-set on first save (when the user favourites the product)
        modify_time  →  auto-updated on every save (rarely changes — favourites are
                        created and deleted, not updated)

    The unique_together constraint mirrors:
        UNIQUE KEY `unique_user_product` (`user_id`, `product_id`)
    in db_market.sql, preventing duplicate entries at both the DB and
    application layers.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,           # mirrors ON DELETE CASCADE in SQL
        related_name='favorites',
        verbose_name='User',
        help_text='The user who favourited the product.',
        db_column='user_id',
    )

    product = models.ForeignKey(
        'product.Product',
        on_delete=models.CASCADE,           # mirrors ON DELETE CASCADE in SQL
        related_name='favorited_by',
        verbose_name='Product',
        help_text='The product that was favourited.',
        db_column='product_id',
    )

    # create_time, modify_time → inherited from TimeStampMixin

    # ------------------------------------------------------------------
    # Meta
    # ------------------------------------------------------------------
    class Meta:
        app_label = 'favorite'
        db_table            = 'favorites'   # exact table name from db_market.sql
        verbose_name        = 'Favourite'
        verbose_name_plural = 'Favourites'
        ordering            = ['-create_time']
        constraints = [
            # Application-layer enforcement of the DB unique constraint
            models.UniqueConstraint(
                fields=['user', 'product'],
                name='unique_user_product',
            )
        ]

    # ------------------------------------------------------------------
    # String representation
    # ------------------------------------------------------------------
    def __str__(self):
        return (
            f'{self.user.username} ♥ '
            f'[{self.product.sn}] {self.product.name}'
        )
