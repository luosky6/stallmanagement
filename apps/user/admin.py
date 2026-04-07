"""
apps/user/admin.py
==================
Django admin configuration for the User model.

Because we use a custom AbstractBaseUser, we must register a custom
ModelAdmin rather than using Django's built-in UserAdmin directly.
We do inherit from UserAdmin to get the password-change form and the
correct field groupings for free, then override only what differs.

What is registered
------------------
UserAdmin   →  User model
             - List: id, username, name, role, is_active, is_deleted, create_time
             - Filters: role, is_active, is_deleted
             - Search: username, name
             - Fieldsets: Account info / Permissions / Important dates
             - Custom action: soft_delete_selected
"""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.html import format_html

from .models import User


# ---------------------------------------------------------------------------
# Inline: show DRF token next to the user (read-only convenience field)
# ---------------------------------------------------------------------------
class AuthTokenInline(admin.TabularInline):
    """
    Shows the user's current DRF auth token in the user detail page.
    Read-only — tokens are created automatically on login.
    """
    from rest_framework.authtoken.models import Token as AuthToken
    model        = AuthToken
    extra        = 0
    readonly_fields = ('key', 'created')
    can_delete   = True
    verbose_name = 'Auth Token'


# ---------------------------------------------------------------------------
# Main UserAdmin
# ---------------------------------------------------------------------------
@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """
    Custom admin for the StallManagement User model.

    Inherits from Django's BaseUserAdmin to get:
    - Password hashing form on the change page
    - The "change password" link in the admin
    """

    # ── List view ───────────────────────────────────────────────────────
    list_display  = ('id', 'username', 'name', 'role_badge', 'is_active', 'is_deleted', 'create_time')
    list_filter   = ('role', 'is_active', 'is_deleted')
    search_fields = ('username', 'name')
    ordering      = ('username',)
    list_per_page = 25

    # ── Detail / change view ─────────────────────────────────────────────
    # Override BaseUserAdmin's fieldsets (which reference fields we don't have,
    # like email, first_name, last_name) with our own field layout.
    fieldsets = (
        (
            'Account',
            {
                'fields': ('username', 'password', 'name'),
            },
        ),
        (
            'Role & Status',
            {
                'fields': ('role', 'is_active', 'is_deleted', 'deleted_at'),
            },
        ),
        (
            'Django Permissions',
            {
                'classes': ('collapse',),
                'fields':  ('is_superuser', 'groups', 'user_permissions'),
            },
        ),
        (
            'Timestamps',
            {
                'classes': ('collapse',),
                'fields':  ('create_time', 'modify_time'),
            },
        ),
    )

    # Fields shown on the "add user" form (simpler than the edit form)
    add_fieldsets = (
        (
            None,
            {
                'classes': ('wide',),
                'fields':  ('username', 'name', 'role', 'password1', 'password2', 'is_active'),
            },
        ),
    )

    # Read-only fields (auto-set or soft-delete metadata)
    readonly_fields = ('create_time', 'modify_time', 'deleted_at')

    # Inline token display
    inlines = []   # AuthTokenInline omitted here to avoid circular import at module load;
                   # uncomment the line below after confirming DRF is installed:
    # inlines = [AuthTokenInline]

    # ── Custom display methods ───────────────────────────────────────────
    @admin.display(description='Role')
    def role_badge(self, obj):
        """Render the role as a coloured badge in the list view."""
        colour_map = {
            'admin':       '#e53e3e',   # red
            'stall_owner': '#ed8936',   # orange
            'customer':    '#38a169',   # green
        }
        colour = colour_map.get(obj.role, '#718096')
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 8px;'
            'border-radius:999px;font-size:11px;">{}</span>',
            colour,
            obj.get_role_display(),
        )

    # ── Custom admin actions ─────────────────────────────────────────────
    actions = ['soft_delete_selected', 'restore_selected', 'activate_selected', 'deactivate_selected']

    @admin.action(description='Soft-delete selected users')
    def soft_delete_selected(self, request, queryset):
        count = 0
        for user in queryset:
            if not user.is_deleted and user != request.user:
                user.delete()   # SoftDeleteMixin.delete()
                count += 1
        self.message_user(request, f'{count} user(s) soft-deleted.')

    @admin.action(description='Restore selected soft-deleted users')
    def restore_selected(self, request, queryset):
        count = 0
        for user in queryset:
            if user.is_deleted:
                user.restore()
                count += 1
        self.message_user(request, f'{count} user(s) restored.')

    @admin.action(description='Activate selected users')
    def activate_selected(self, request, queryset):
        updated = queryset.update(is_active=True)
        self.message_user(request, f'{updated} user(s) activated.')

    @admin.action(description='Deactivate selected users')
    def deactivate_selected(self, request, queryset):
        # Prevent admins from deactivating their own account
        count = queryset.exclude(pk=request.user.pk).update(is_active=False)
        self.message_user(request, f'{count} user(s) deactivated.')
