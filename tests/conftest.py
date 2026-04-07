"""
tests/conftest.py
=================
Pytest configuration and shared fixtures for the StallManagement test suite.

Running the tests
-----------------
    # All tests
    pytest

    # Specific module
    pytest tests/test_product.py -v

    # With coverage
    pytest --cov=apps --cov=utils --cov-report=term-missing

    # Stop on first failure
    pytest -x

    # Run only tests matching a keyword
    pytest -k "stock"

Django setup
------------
Pytest-django is used so Django is initialised before any test runs.
The DJANGO_SETTINGS_MODULE env var is picked up from pytest.ini / pyproject.toml,
or can be set here via django_settings (see below).

Fixture naming conventions
--------------------------
  admin_user          User with role='admin'
  stall_owner_user    User with role='stall_owner'
  customer_user       User with role='customer'
  api_client          DRF APIClient (unauthenticated)
  admin_client        APIClient authenticated as admin
  owner_client        APIClient authenticated as stall_owner
  customer_client     APIClient authenticated as customer
  category            A single Category instance
  product             A single Product instance (stock=100)
  low_stock_product   A Product with stock=5 (below threshold)
  supplier            A Customer with type='supplier'
  buyer               A Customer with type='buyer'
  stall               A Stall owned by stall_owner_user
  draft_inorder       A draft InOrder with one line
  draft_outorder      A draft OutOrder with one line
"""

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework.authtoken.models import Token

from apps.category.models import Category
from apps.product.models import Product
from apps.customer.models import Customer
from apps.stall.models import Stall
from apps.inorder.models import InOrder, InOrderProduct
from apps.outorder.models import OutOrder, OutOrderProduct

User = get_user_model()


# ---------------------------------------------------------------------------
# pytest-django marker — all tests use the DB unless marked otherwise
# ---------------------------------------------------------------------------
pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# User fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def admin_user(db):
    """A User instance with role='admin'."""
    return User.objects.create_superuser(
        username='testadmin',
        password='AdminPass123!',
        name='Test Admin',
    )


@pytest.fixture
def stall_owner_user(db):
    """A User instance with role='stall_owner'."""
    return User.objects.create_user(
        username='testowner',
        password='OwnerPass123!',
        name='Test Owner',
        role='stall_owner',
    )


@pytest.fixture
def customer_user(db):
    """A User instance with role='customer'."""
    return User.objects.create_user(
        username='testcustomer',
        password='CustomerPass123!',
        name='Test Customer',
        role='customer',
    )


@pytest.fixture
def second_customer_user(db):
    """A second customer for chat pairing tests."""
    return User.objects.create_user(
        username='testcustomer2',
        password='CustomerPass123!',
        name='Test Customer Two',
        role='customer',
    )


# ---------------------------------------------------------------------------
# API client fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def api_client():
    """An unauthenticated DRF APIClient."""
    return APIClient()


def _authenticated_client(user):
    """Helper: create and return an APIClient authenticated with a DRF token."""
    client = APIClient()
    token, _ = Token.objects.get_or_create(user=user)
    client.credentials(HTTP_AUTHORIZATION=f'Token {token.key}')
    return client


@pytest.fixture
def admin_client(db, admin_user):
    """APIClient authenticated as the admin user."""
    return _authenticated_client(admin_user)


@pytest.fixture
def owner_client(db, stall_owner_user):
    """APIClient authenticated as the stall_owner user."""
    return _authenticated_client(stall_owner_user)


@pytest.fixture
def customer_client(db, customer_user):
    """APIClient authenticated as the customer user."""
    return _authenticated_client(customer_user)


# ---------------------------------------------------------------------------
# Domain fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def category(db):
    """A single Category instance: 'Clothing'."""
    return Category.objects.create(
        name='Clothing',
        description='Clothes, shoes, accessories',
    )


@pytest.fixture
def electronics_category(db):
    """A second Category instance: 'Electronics'."""
    return Category.objects.create(
        name='Electronics',
        description='Mobile phones, tablets, accessories',
    )


@pytest.fixture
def product(db, category):
    """A Product with stock=100 (well above the low-stock threshold)."""
    return Product.objects.create(
        sn='CLT-001',
        name="Men's T-Shirt",
        price='59.99',
        category=category,
        stock=100,
        description='Premium cotton t-shirt',
    )


@pytest.fixture
def low_stock_product(db, category):
    """A Product with stock=5 (below LOW_STOCK_THRESHOLD=20)."""
    return Product.objects.create(
        sn='CLT-002',
        name="Women's Dress",
        price='129.99',
        category=category,
        stock=5,
        description='Fashionable fitted dress',
    )


@pytest.fixture
def zero_stock_product(db, category):
    """A Product with stock=0 (out of stock)."""
    return Product.objects.create(
        sn='CLT-003',
        name='Winter Jacket',
        price='399.99',
        category=category,
        stock=0,
        description='Warm and windproof winter jacket',
    )


@pytest.fixture
def supplier(db):
    """A Customer with type='supplier'."""
    return Customer.objects.create(
        name='Supplier A',
        phone='13800000001',
        address='Clementi West Street',
        customer_type='supplier',
    )


@pytest.fixture
def buyer(db):
    """A Customer with type='buyer'."""
    return Customer.objects.create(
        name='Buyer C',
        phone='13800000003',
        address='Pioneer Road',
        customer_type='buyer',
    )


@pytest.fixture
def stall(db, stall_owner_user):
    """An active Stall owned by stall_owner_user."""
    return Stall.objects.create(
        name='Test Stall',
        owner=stall_owner_user,
        description='A test stall',
        status='active',
    )


@pytest.fixture
def draft_inorder(db, supplier, stall_owner_user, product):
    """A draft InOrder with one line item (product × 50, unit_price=50.00)."""
    order = InOrder.objects.create(
        code='IN20241201001',
        customer=supplier,
        operator=stall_owner_user,
        status='draft',
        remark='',
    )
    InOrderProduct.objects.create(
        inorder=order,
        product=product,
        amount=50,
        unit_price='50.00',
    )
    return order


@pytest.fixture
def draft_outorder(db, buyer, stall_owner_user, product):
    """A draft OutOrder with one line item (product × 20, unit_price=59.99)."""
    order = OutOrder.objects.create(
        code='OUT20241201001',
        customer=buyer,
        operator=stall_owner_user,
        status='draft',
        remark='',
    )
    OutOrderProduct.objects.create(
        outorder=order,
        product=product,
        amount=20,
        unit_price='59.99',
    )
    return order


# ---------------------------------------------------------------------------
# Shared assertion helpers
# ---------------------------------------------------------------------------
def assert_ok(response, code=200):
    """Assert the response has the standard success envelope and expected HTTP code."""
    assert response.status_code == code, (
        f'Expected HTTP {code}, got {response.status_code}. '
        f'Body: {response.data}'
    )
    assert response.data['success'] is True
    return response.data.get('data')


def assert_fail(response, code=400):
    """Assert the response has the standard failure envelope and expected HTTP code."""
    assert response.status_code == code, (
        f'Expected HTTP {code}, got {response.status_code}. '
        f'Body: {response.data}'
    )
    assert response.data['success'] is False
    return response.data
