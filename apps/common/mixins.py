"""
apps/common/mixins.py
=====================
Abstract base model mixins shared across all apps.

These mixins are NOT standalone models — they have no database table of their
own (abstract = True).  Every concrete model that inherits from them gets the
mixin fields merged into its own table automatically by Django.

Usage example (in any app's models.py):
    from apps.common.mixins import TimeStampMixin, SoftDeleteMixin

    class Product(TimeStampMixin):          # adds create_time + modify_time
        name = models.CharField(...)

    class User(TimeStampMixin, SoftDeleteMixin):  # adds timestamps + is_deleted
        username = models.CharField(...)
"""

from django.db import models
from django.utils import timezone


# ---------------------------------------------------------------------------
# 1. TimeStampMixin
#    Adds create_time and modify_time to any model that inherits it.
#    Maps to the pattern used in every table in db_market.sql:
#       `create_time` DATETIME DEFAULT CURRENT_TIMESTAMP
#       `modify_time` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
# ---------------------------------------------------------------------------
class TimeStampMixin(models.Model):
    """
    Provides automatic create_time and modify_time timestamp fields.

    - create_time : set once when the record is first saved (auto_now_add)
    - modify_time : updated automatically on every subsequent save (auto_now)
    """

    create_time = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Creation Time',
        help_text='Timestamp when this record was created (set automatically).',
    )
    modify_time = models.DateTimeField(
        auto_now=True,
        verbose_name='Modification Time',
        help_text='Timestamp of the last update (updated automatically).',
    )

    class Meta:
        abstract = True   # No database table is created for this mixin itself


# ---------------------------------------------------------------------------
# 2. SoftDeleteMixin
#    Adds is_deleted flag and a custom manager so that deleted records are
#    excluded from normal querysets but can still be retrieved when needed.
#    Maps to:
#       `is_deleted` TINYINT(1) DEFAULT 0  (in the users table)
# ---------------------------------------------------------------------------
class SoftDeleteManager(models.Manager):
    """
    Default manager that automatically filters out soft-deleted records.
    Use Model.all_objects.all() to include deleted records.
    """

    def get_queryset(self):
        return super().get_queryset().filter(is_deleted=False)


class SoftDeleteAllManager(models.Manager):
    """
    Unfiltered manager — returns ALL records including soft-deleted ones.
    Attach this as `all_objects` on any SoftDeleteMixin model.
    """

    def get_queryset(self):
        return super().get_queryset()


class SoftDeleteMixin(models.Model):
    """
    Provides a soft-delete mechanism via the is_deleted boolean flag.

    Instead of physically removing a row with DELETE, call instance.delete()
    which sets is_deleted=True and saves.  The default manager (objects)
    hides soft-deleted rows automatically.  Use all_objects to see them.

    Methods
    -------
    delete()        — soft delete (sets is_deleted=True, records deleted_at)
    hard_delete()   — physically removes the row from the database
    restore()       — reverses a soft delete (sets is_deleted=False)
    """

    is_deleted = models.BooleanField(
        default=False,
        verbose_name='Soft Deleted',
        help_text='True means this record is logically deleted and hidden from normal queries.',
    )
    deleted_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Deletion Time',
        help_text='Timestamp when this record was soft-deleted.',
    )

    # Managers
    objects     = SoftDeleteManager()      # default: excludes deleted rows
    all_objects = SoftDeleteAllManager()   # includes deleted rows

    class Meta:
        abstract = True

    # ------------------------------------------------------------------ #
    # Override delete() so ORM-level .delete() performs a soft delete.    #
    # ------------------------------------------------------------------ #
    def delete(self, using=None, keep_parents=False):
        """
        Soft delete: marks the record as deleted without removing the row.
        Sets is_deleted=True and records the deletion timestamp.
        """
        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.save(update_fields=['is_deleted', 'deleted_at'])

    def hard_delete(self, using=None, keep_parents=False):
        """
        Physical delete: permanently removes the row from the database.
        Use with caution — this cannot be reversed.
        """
        super().delete(using=using, keep_parents=keep_parents)

    def restore(self):
        """
        Restore a soft-deleted record: clears is_deleted and deleted_at.
        """
        self.is_deleted = False
        self.deleted_at = None
        self.save(update_fields=['is_deleted', 'deleted_at'])


# ---------------------------------------------------------------------------
# 3. TimeStampSoftDeleteMixin
#    Convenience mixin combining both TimeStampMixin and SoftDeleteMixin.
#    Used by the User model which needs both timestamp fields AND is_deleted.
# ---------------------------------------------------------------------------
class TimeStampSoftDeleteMixin(TimeStampMixin, SoftDeleteMixin):
    """
    Combined mixin: create_time + modify_time + is_deleted + deleted_at.
    Inherit this when you need all four fields in one shot.
    """

    class Meta:
        abstract = True
