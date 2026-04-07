"""
apps/user/models.py
===================
Custom User model for the StallManagement project.

Why AbstractBaseUser (not the default auth.User)?
-------------------------------------------------
The db_market.sql `users` table has:
  - A custom `role` ENUM field  ('admin' | 'stall_owner' | 'customer')
  - A custom `name` field       (real / display name, separate from username)
  - A custom `is_deleted` flag  (soft-delete, not present in auth.User)
  - No `email`, `first_name`, `last_name`, `last_login` (not needed)

Django's built-in User model cannot map cleanly to this schema, so we
extend AbstractBaseUser and define exactly the fields we need.

IMPORTANT
---------
settings.py must declare:
    AUTH_USER_MODEL = 'user.User'
This must be set before the first migration is run. Changing it afterwards
requires resetting all migrations.

Database table: `users`  (matches db_market.sql table name)
"""

from django.db import models
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin

from apps.common.mixins import TimeStampSoftDeleteMixin
from .managers import CustomUserManager


class User(AbstractBaseUser, PermissionsMixin, TimeStampSoftDeleteMixin):
    """
    Custom User model.

    Inherits from
    -------------
    AbstractBaseUser
        Provides: password hashing, last_login, is_active, get_full_name(),
                  get_short_name(), has_perm(), has_module_perms().
    PermissionsMixin
        Provides: is_superuser, groups (M2M), user_permissions (M2M).
        Needed to make the Django admin panel work correctly.
    TimeStampSoftDeleteMixin
        Provides: create_time, modify_time, is_deleted, deleted_at.

    Fields (all map directly to columns in db_market.sql `users` table)
    -------------------------------------------------------------------
    id          AUTO_INCREMENT PK          (from Django)
    username    VARCHAR(50) UNIQUE NOT NULL
    password    VARCHAR(128) NOT NULL       (hashed — managed by AbstractBaseUser)
    name        VARCHAR(50) NOT NULL        (real / display name)
    role        ENUM(admin|stall_owner|customer)
    is_active   TINYINT(1) DEFAULT 1
    is_deleted  TINYINT(1) DEFAULT 0       (from SoftDeleteMixin)
    deleted_at  DATETIME NULL              (from SoftDeleteMixin)
    create_time DATETIME                   (from TimeStampMixin)
    modify_time DATETIME                   (from TimeStampMixin)
    """

    # ------------------------------------------------------------------
    # Role choices — mirror the ENUM in db_market.sql
    # ------------------------------------------------------------------
    class Role(models.TextChoices):
        ADMIN       = 'admin',       'Admin'
        STALL_OWNER = 'stall_owner', 'Stall Owner'
        CUSTOMER    = 'customer',    'Customer'

    # ------------------------------------------------------------------
    # Fields
    # ------------------------------------------------------------------
    username = models.CharField(
        max_length=50,
        unique=True,
        verbose_name='Username',
        help_text='Required. 50 characters or fewer. Lowercase letters, digits, and underscores.',
        error_messages={
            'unique': 'A user with that username already exists.',
        },
    )

    # password is inherited from AbstractBaseUser (hashed via PBKDF2)

    name = models.CharField(
        max_length=50,
        verbose_name='Display Name',
        help_text='Real name or display name shown in the UI.',
    )

    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.CUSTOMER,
        verbose_name='Role',
        help_text='Determines what the user can access in the system.',
    )

    is_active = models.BooleanField(
        default=True,
        verbose_name='Active',
        help_text=(
            'Designates whether this user account should be treated as active. '
            'Unselect this instead of deleting accounts.'
        ),
    )

    # is_deleted, deleted_at  →  inherited from SoftDeleteMixin
    # create_time, modify_time →  inherited from TimeStampMixin

    # ------------------------------------------------------------------
    # Manager
    # ------------------------------------------------------------------
    # 'objects' replaces Django's default manager.
    # Automatically excludes soft-deleted users from every queryset.
    # Use User.all_objects.all() to include deleted records.
    objects = CustomUserManager()

    # ------------------------------------------------------------------
    # AbstractBaseUser required settings
    # ------------------------------------------------------------------
    # The field used as the unique identifier for authentication
    USERNAME_FIELD  = 'username'

    # Fields prompted by manage.py createsuperuser (besides USERNAME_FIELD)
    REQUIRED_FIELDS = ['name']

    # ------------------------------------------------------------------
    # Meta
    # ------------------------------------------------------------------
    class Meta:
        app_label = 'user'
        db_table    = 'users'          # exact table name from db_market.sql
        verbose_name        = 'User'
        verbose_name_plural = 'Users'
        ordering = ['username']

    # ------------------------------------------------------------------
    # String representation
    # ------------------------------------------------------------------
    def __str__(self):
        return f'{self.username} ({self.get_role_display()})'

    # ------------------------------------------------------------------
    # AbstractBaseUser required methods
    # ------------------------------------------------------------------
    def get_full_name(self):
        """Return the display name (used by Django internals and admin)."""
        return self.name

    def get_short_name(self):
        """Return the username as the short identifier."""
        return self.username

    # ------------------------------------------------------------------
    # Role helper properties
    # ------------------------------------------------------------------
    @property
    def is_admin(self):
        """True if this user has the admin role."""
        return self.role == self.Role.ADMIN

    @property
    def is_stall_owner(self):
        """True if this user has the stall_owner role."""
        return self.role == self.Role.STALL_OWNER

    @property
    def is_customer(self):
        """True if this user has the customer role."""
        return self.role == self.Role.CUSTOMER

    # ------------------------------------------------------------------
    # Django admin compatibility
    # is_staff is required by the Django admin — map it to is_admin
    # so only users with role='admin' can access the /admin/ panel.
    # ------------------------------------------------------------------
    @property
    def is_staff(self):
        """Grants Django admin panel access to admin-role users."""
        return self.role == self.Role.ADMIN
