"""
tests/test_user.py
==================
Tests for the custom User model, authentication, and user management API.

Coverage
--------
- User model: creation, password hashing, role helpers, soft-delete
- CustomUserManager: create_user, create_superuser, by_role, soft-delete filter
- Login / logout REST endpoints
- User CRUD API (admin only)
- Role-based access control (403 for wrong roles)
- Password change endpoint
- Soft-delete and restore
"""

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from tests.conftest import assert_ok, assert_fail

User = get_user_model()
pytestmark = pytest.mark.django_db


# ===========================================================================
# User model unit tests
# ===========================================================================
class TestUserModel:

    def test_create_user_hashes_password(self):
        user = User.objects.create_user(
            username='hashtest',
            password='PlainText123!',
            name='Hash Test',
            role='customer',
        )
        # Password must NOT be stored as plain text
        assert user.password != 'PlainText123!'
        assert user.check_password('PlainText123!') is True

    def test_create_superuser_sets_admin_role(self):
        admin = User.objects.create_superuser(
            username='supertest',
            password='AdminPass123!',
            name='Super Test',
        )
        assert admin.role == 'admin'
        assert admin.is_active is True
        assert admin.is_staff is True         # maps to role == 'admin'
        assert admin.is_superuser is True

    def test_role_helper_properties(self):
        admin   = User.objects.create_user('r_admin',   'pass', 'Admin',   role='admin')
        owner   = User.objects.create_user('r_owner',   'pass', 'Owner',   role='stall_owner')
        customer = User.objects.create_user('r_cust',   'pass', 'Cust',    role='customer')

        assert admin.is_admin        is True
        assert admin.is_stall_owner  is False
        assert admin.is_customer     is False

        assert owner.is_admin        is False
        assert owner.is_stall_owner  is True
        assert owner.is_customer     is False

        assert customer.is_admin     is False
        assert customer.is_stall_owner is False
        assert customer.is_customer  is True

    def test_is_staff_maps_to_admin_role(self):
        owner = User.objects.create_user('owner_staff', 'pass', 'Owner', role='stall_owner')
        assert owner.is_staff is False

    def test_soft_delete_hides_user_from_default_manager(self):
        user = User.objects.create_user('softdel', 'pass', 'Soft Del', role='customer')
        user_id = user.id
        user.delete()   # SoftDeleteMixin.delete()

        # Default manager must not return the deleted user
        assert not User.objects.filter(pk=user_id).exists()
        # all_objects manager must still find it
        assert User.all_objects.filter(pk=user_id, is_deleted=True).exists()

    def test_soft_delete_sets_deleted_at(self):
        user = User.objects.create_user('softdel2', 'pass', 'Soft Del2', role='customer')
        assert user.deleted_at is None
        user.delete()
        user.refresh_from_db()
        assert user.is_deleted is True
        assert user.deleted_at is not None

    def test_restore_clears_deleted_flag(self):
        user = User.objects.create_user('restore1', 'pass', 'Restore', role='customer')
        user.delete()
        user.restore()
        assert user.is_deleted is False
        assert user.deleted_at is None
        # Default manager should find it again
        assert User.objects.filter(pk=user.id).exists()

    def test_manager_by_role(self):
        User.objects.create_user('role1', 'pass', 'Role1', role='admin')
        User.objects.create_user('role2', 'pass', 'Role2', role='customer')
        User.objects.create_user('role3', 'pass', 'Role3', role='stall_owner')

        assert User.objects.by_role('admin').filter(username='role1').exists()
        assert User.objects.customers().filter(username='role2').exists()
        assert User.objects.stall_owners().filter(username='role3').exists()

    def test_username_normalised_to_lowercase(self):
        user = User.objects.create_user('UPPERCASE', 'pass', 'Upper', role='customer')
        assert user.username == 'uppercase'


# ===========================================================================
# Authentication API tests
# ===========================================================================
class TestAuthAPI:

    def test_login_success_returns_token_and_role(self, api_client, customer_user):
        response = api_client.post('/api/auth/login/', {
            'username': 'testcustomer',
            'password': 'CustomerPass123!',
        })
        data = assert_ok(response, code=200)
        assert 'token' in data
        assert data['user']['role'] == 'customer'
        assert data['user']['username'] == 'testcustomer'

    def test_login_normalizes_username_case(self, api_client, customer_user):
        response = api_client.post('/api/auth/login/', {
            'username': 'TESTCUSTOMER',
            'password': 'CustomerPass123!',
        })
        data = assert_ok(response, code=200)
        assert data['user']['username'] == 'testcustomer'

    def test_login_wrong_password_returns_401(self, api_client, customer_user):
        response = api_client.post('/api/auth/login/', {
            'username': 'testcustomer',
            'password': 'WrongPassword!',
        })
        assert_fail(response, code=401)

    def test_login_nonexistent_user_returns_401(self, api_client):
        response = api_client.post('/api/auth/login/', {
            'username': 'nobody',
            'password': 'NoPass123!',
        })
        assert_fail(response, code=401)

    def test_login_missing_fields_returns_400(self, api_client):
        response = api_client.post('/api/auth/login/', {'username': 'only'})
        assert_fail(response, code=400)

    def test_register_creates_customer_account_and_returns_token(self, api_client):
        response = api_client.post('/api/auth/register/', {
            'username': 'newcustomer',
            'name': 'New Customer',
            'password': 'CustomerPass123!',
            'password_confirm': 'CustomerPass123!',
        })
        data = assert_ok(response, code=201)
        assert 'token' in data
        assert data['user']['username'] == 'newcustomer'
        assert data['user']['role'] == 'customer'
        assert User.objects.get(username='newcustomer').check_password('CustomerPass123!')

    def test_register_duplicate_username_returns_400(self, api_client, customer_user):
        response = api_client.post('/api/auth/register/', {
            'username': 'testcustomer',
            'name': 'Duplicate Customer',
            'password': 'CustomerPass123!',
            'password_confirm': 'CustomerPass123!',
        })
        assert_fail(response, code=400)

    def test_forgot_password_resets_password_after_display_name_match(self, api_client, customer_user):
        response = api_client.post('/api/auth/forgot-password/', {
            'username': 'testcustomer',
            'name': 'Test Customer',
            'new_password': 'ResetPass123!',
            'new_password_confirm': 'ResetPass123!',
        })
        assert_ok(response)

        old_login = api_client.post('/api/auth/login/', {
            'username': 'testcustomer',
            'password': 'CustomerPass123!',
        })
        assert_fail(old_login, code=401)

        new_login = api_client.post('/api/auth/login/', {
            'username': 'testcustomer',
            'password': 'ResetPass123!',
        })
        assert_ok(new_login)

    def test_forgot_password_rejects_wrong_display_name(self, api_client, customer_user):
        response = api_client.post('/api/auth/forgot-password/', {
            'username': 'testcustomer',
            'name': 'Wrong Name',
            'new_password': 'ResetPass123!',
            'new_password_confirm': 'ResetPass123!',
        })
        assert_fail(response, code=400)

    def test_logout_invalidates_token(self, owner_client, stall_owner_user):
        # Confirm we can access a protected endpoint before logout
        pre = owner_client.get('/api/auth/me/')
        assert pre.status_code == 200

        # Logout
        owner_client.post('/api/auth/logout/')

        # Token should now be invalid — same client, same credentials
        post = owner_client.get('/api/auth/me/')
        assert post.status_code == 401

    def test_me_returns_current_user(self, customer_client, customer_user):
        response = customer_client.get('/api/auth/me/')
        data = assert_ok(response)
        assert data['username'] == 'testcustomer'
        assert data['role'] == 'customer'

    def test_unauthenticated_me_returns_401(self, api_client):
        response = api_client.get('/api/auth/me/')
        assert response.status_code == 401


# ===========================================================================
# User CRUD API tests
# ===========================================================================
class TestUserCRUDAPI:

    def test_admin_can_list_users(self, admin_client, admin_user, customer_user):
        response = admin_client.get('/api/users/')
        data = assert_ok(response)
        assert data['total'] >= 2

    def test_stall_owner_cannot_list_users(self, owner_client):
        response = owner_client.get('/api/users/')
        assert response.status_code == 403

    def test_customer_cannot_list_users(self, customer_client):
        response = customer_client.get('/api/users/')
        assert response.status_code == 403

    def test_admin_can_create_user(self, admin_client):
        response = admin_client.post('/api/users/', {
            'username':         'newuser',
            'password':         'NewPass123!',
            'password_confirm': 'NewPass123!',
            'name':             'New User',
            'role':             'customer',
        })
        data = assert_ok(response, code=201)
        assert data['username'] == 'newuser'
        assert data['role'] == 'customer'

    def test_create_user_duplicate_username_returns_400(self, admin_client, customer_user):
        response = admin_client.post('/api/users/', {
            'username':         'testcustomer',
            'password':         'Pass123!',
            'password_confirm': 'Pass123!',
            'name':             'Duplicate',
            'role':             'customer',
        })
        assert_fail(response, code=400)

    def test_create_user_password_mismatch_returns_400(self, admin_client):
        response = admin_client.post('/api/users/', {
            'username':         'mismatch',
            'password':         'Pass123!',
            'password_confirm': 'Different123!',
            'name':             'Mismatch',
            'role':             'customer',
        })
        assert_fail(response, code=400)

    def test_admin_can_retrieve_user(self, admin_client, customer_user):
        response = admin_client.get(f'/api/users/{customer_user.id}/')
        data = assert_ok(response)
        assert data['username'] == 'testcustomer'

    def test_admin_can_update_user_name(self, admin_client, customer_user):
        response = admin_client.patch(f'/api/users/{customer_user.id}/', {
            'name': 'Updated Name',
        })
        data = assert_ok(response)
        assert data['name'] == 'Updated Name'

    def test_admin_can_soft_delete_user(self, admin_client, customer_user):
        response = admin_client.delete(f'/api/users/{customer_user.id}/delete/')
        assert_ok(response)
        # User must be hidden from default manager
        assert not User.objects.filter(pk=customer_user.id).exists()

    def test_admin_cannot_delete_self(self, admin_client, admin_user):
        response = admin_client.delete(f'/api/users/{admin_user.id}/delete/')
        assert_fail(response, code=403)

    def test_admin_can_restore_soft_deleted_user(self, admin_client, customer_user):
        customer_user.delete()
        response = admin_client.post(f'/api/users/{customer_user.id}/restore/')
        data = assert_ok(response)
        assert data['is_deleted'] is False  # or check username

    def test_filter_users_by_role(self, admin_client, admin_user, customer_user, stall_owner_user):
        response = admin_client.get('/api/users/?role=customer')
        data = assert_ok(response)
        assert all(u['role'] == 'customer' for u in data['results'])

    def test_admin_can_list_deleted_users_when_requested(self, admin_client, customer_user):
        customer_user.delete()
        response = admin_client.get('/api/users/?include_deleted=true')
        data = assert_ok(response)
        assert any(u['username'] == 'testcustomer' and u['is_deleted'] is True for u in data['results'])

    def test_admin_can_list_only_deleted_users(self, admin_client, customer_user, stall_owner_user):
        customer_user.delete()
        response = admin_client.get('/api/users/?deleted_only=true')
        data = assert_ok(response)
        assert data['results']
        assert all(u['is_deleted'] is True for u in data['results'])

    def test_change_password_success(self, customer_client, customer_user):
        response = customer_client.post('/api/users/change_password/', {
            'current_password':     'CustomerPass123!',
            'new_password':         'NewSecure456!',
            'new_password_confirm': 'NewSecure456!',
        })
        data = assert_ok(response)
        # A new token should be issued
        assert 'token' in data

    def test_change_password_wrong_current(self, customer_client):
        response = customer_client.post('/api/users/change_password/', {
            'current_password':     'WrongCurrent!',
            'new_password':         'NewSecure456!',
            'new_password_confirm': 'NewSecure456!',
        })
        assert_fail(response, code=400)
