"""
tests/test_product.py
=====================
Tests for the Product model, serializers, and REST API.

Coverage
--------
- Product model: field validation, helper properties, order-line guards
- Product CRUD API: create, retrieve, update, delete
- Search and filter: by category, stock_status, price range, text search
- Stock field write protection (blocked via PATCH)
- Low-stock endpoint
- Lookup endpoint for order form dropdowns
- Permission checks: customer read-only, admin/stall_owner write
- Deletion guard: cannot delete product referenced by an order line
"""

import pytest
from decimal import Decimal

from apps.product.models import Product, LOW_STOCK_THRESHOLD
from apps.inorder.models import InOrderProduct
from tests.conftest import assert_ok, assert_fail

pytestmark = pytest.mark.django_db


# ===========================================================================
# Product model unit tests
# ===========================================================================
class TestProductModel:

    def test_str_representation(self, product):
        assert '[CLT-001]' in str(product)
        assert "Men's T-Shirt" in str(product)

    def test_is_low_stock_false_above_threshold(self, product):
        product.stock = LOW_STOCK_THRESHOLD
        assert product.is_low_stock is False

    def test_is_low_stock_true_below_threshold(self, low_stock_product):
        assert low_stock_product.stock < LOW_STOCK_THRESHOLD
        assert low_stock_product.is_low_stock is True

    def test_is_out_of_stock(self, zero_stock_product):
        assert zero_stock_product.is_out_of_stock is True

    def test_is_not_out_of_stock_when_stock_positive(self, product):
        assert product.is_out_of_stock is False

    def test_has_no_order_lines_initially(self, product):
        assert product.has_any_order_lines is False

    def test_has_inbound_order_lines_after_creation(self, draft_inorder, product):
        assert product.has_inbound_order_lines is True
        assert product.has_any_order_lines is True

    def test_sn_unique_constraint(self, db, category):
        Product.objects.create(sn='UNIQ-001', name='A', price='10', category=category, stock=10)
        with pytest.raises(Exception):
            Product.objects.create(sn='UNIQ-001', name='B', price='20', category=category, stock=5)


# ===========================================================================
# Product API: Create
# ===========================================================================
class TestProductCreate:

    def test_admin_can_create_product(self, admin_client, category):
        response = admin_client.post('/api/products/', {
            'sn':          'NEW-001',
            'name':        'New Product',
            'price':       '49.99',
            'category_id': category.id,
            'stock':       50,
            'description': 'A brand new product',
        })
        data = assert_ok(response, code=201)
        assert data['sn'] == 'NEW-001'
        assert data['stock'] == 50

    def test_owner_can_create_product(self, owner_client, category):
        response = owner_client.post('/api/products/', {
            'sn':          'OWN-001',
            'name':        'Owner Product',
            'price':       '19.99',
            'category_id': category.id,
        })
        assert_ok(response, code=201)

    def test_customer_cannot_create_product(self, customer_client, category):
        response = customer_client.post('/api/products/', {
            'sn':          'CUST-001',
            'name':        'Forbidden',
            'price':       '9.99',
            'category_id': category.id,
        })
        assert response.status_code == 403

    def test_unauthenticated_cannot_create(self, api_client, category):
        response = api_client.post('/api/products/', {
            'sn': 'X-001', 'name': 'X', 'price': '1', 'category_id': category.id
        })
        assert response.status_code == 401

    def test_duplicate_sn_returns_400(self, admin_client, product, category):
        response = admin_client.post('/api/products/', {
            'sn':          'CLT-001',   # already exists
            'name':        'Dup',
            'price':       '10',
            'category_id': category.id,
        })
        assert_fail(response, code=400)

    def test_negative_price_returns_400(self, admin_client, category):
        response = admin_client.post('/api/products/', {
            'sn':          'NEG-001',
            'name':        'Negative',
            'price':       '-5.00',
            'category_id': category.id,
        })
        assert_fail(response, code=400)

    def test_invalid_category_id_returns_400(self, admin_client):
        response = admin_client.post('/api/products/', {
            'sn':          'BADCAT-001',
            'name':        'Bad Cat',
            'price':       '10',
            'category_id': 99999,
        })
        assert_fail(response, code=400)

    def test_sn_normalised_to_uppercase(self, admin_client, category):
        response = admin_client.post('/api/products/', {
            'sn':          'lower-001',
            'name':        'Lower SN',
            'price':       '10',
            'category_id': category.id,
        })
        data = assert_ok(response, code=201)
        assert data['sn'] == 'LOWER-001'


# ===========================================================================
# Product API: Retrieve and Update
# ===========================================================================
class TestProductRetrieveUpdate:

    def test_customer_can_retrieve_product(self, customer_client, product):
        response = customer_client.get(f'/api/products/{product.id}/')
        data = assert_ok(response)
        assert data['sn'] == 'CLT-001'
        assert 'category' in data
        assert 'stock_status' in data

    def test_response_includes_nested_category(self, owner_client, product):
        response = owner_client.get(f'/api/products/{product.id}/')
        data = assert_ok(response)
        assert data['category']['id'] == product.category_id
        assert data['category']['name'] == 'Clothing'

    def test_owner_can_update_name(self, owner_client, product):
        response = owner_client.patch(f'/api/products/{product.id}/', {
            'name': 'Updated T-Shirt',
        })
        data = assert_ok(response)
        assert data['name'] == 'Updated T-Shirt'

    def test_stock_write_blocked_via_patch(self, owner_client, product):
        """Direct stock edits must be rejected — use orders instead."""
        response = owner_client.patch(f'/api/products/{product.id}/', {
            'stock': 999,
        })
        assert_fail(response, code=400)
        # Stock must remain unchanged
        product.refresh_from_db()
        assert product.stock == 100

    def test_nonexistent_product_returns_404(self, owner_client):
        response = owner_client.get('/api/products/99999/')
        assert response.status_code == 404


# ===========================================================================
# Product API: Delete
# ===========================================================================
class TestProductDelete:

    def test_admin_can_delete_product(self, admin_client, product):
        response = admin_client.delete(f'/api/products/{product.id}/delete/')
        assert_ok(response)
        assert not Product.objects.filter(pk=product.id).exists()

    def test_cannot_delete_product_with_order_lines(self, admin_client, draft_inorder, product):
        """Product referenced by an order line must not be deletable."""
        response = admin_client.delete(f'/api/products/{product.id}/delete/')
        assert_fail(response, code=400)
        assert 'inbound_order_line_count' in response.data.get('data', {})

    def test_customer_cannot_delete_product(self, customer_client, product):
        response = customer_client.delete(f'/api/products/{product.id}/delete/')
        assert response.status_code == 403


# ===========================================================================
# Product API: List, Search, Filter
# ===========================================================================
class TestProductListFilter:

    def test_list_all_products(self, owner_client, product, low_stock_product):
        response = owner_client.get('/api/products/')
        data = assert_ok(response)
        assert data['total'] >= 2

    def test_filter_by_category_id(self, owner_client, product, electronics_category, db):
        elec = Product.objects.create(
            sn='ELEC-T001', name='Test Earbuds', price='99',
            category=electronics_category, stock=50,
        )
        response = owner_client.get(f'/api/products/?category_id={electronics_category.id}')
        data = assert_ok(response)
        ids = [p['id'] for p in data['results']]
        assert elec.id in ids
        assert product.id not in ids

    def test_filter_by_stock_status_low(self, owner_client, product, low_stock_product):
        response = owner_client.get('/api/products/?stock_status=low')
        data = assert_ok(response)
        assert all(
            0 < p['stock'] < LOW_STOCK_THRESHOLD
            for p in data['results']
        )

    def test_filter_by_stock_status_out(self, owner_client, zero_stock_product):
        response = owner_client.get('/api/products/?stock_status=out')
        data = assert_ok(response)
        assert all(p['stock'] == 0 for p in data['results'])

    def test_search_by_name(self, owner_client, product):
        response = owner_client.get('/api/products/?search=T-Shirt')
        data = assert_ok(response)
        assert any('T-Shirt' in p['name'] for p in data['results'])

    def test_search_by_sn(self, owner_client, product):
        response = owner_client.get('/api/products/?search=CLT-001')
        data = assert_ok(response)
        assert data['results'][0]['sn'] == 'CLT-001'

    def test_response_includes_low_stock_threshold(self, owner_client, product):
        response = owner_client.get('/api/products/')
        data = assert_ok(response)
        assert data['low_stock_threshold'] == LOW_STOCK_THRESHOLD

    def test_invalid_stock_status_returns_400(self, owner_client):
        response = owner_client.get('/api/products/?stock_status=invalid')
        assert_fail(response, code=400)


# ===========================================================================
# Product API: Low-stock endpoint
# ===========================================================================
class TestProductLowStock:

    def test_low_stock_returns_only_low_products(
        self, owner_client, product, low_stock_product, zero_stock_product
    ):
        response = owner_client.get('/api/products/low_stock/')
        data = assert_ok(response)
        ids = [p['id'] for p in data['results']]
        # low_stock (5) and zero_stock (0) are both below threshold
        assert low_stock_product.id in ids
        assert zero_stock_product.id in ids
        # product (100) should NOT be in the low-stock list
        assert product.id not in ids

    def test_customer_cannot_access_low_stock(self, customer_client):
        response = customer_client.get('/api/products/low_stock/')
        assert response.status_code == 403


# ===========================================================================
# Product API: Lookup endpoint
# ===========================================================================
class TestProductLookup:

    def test_lookup_returns_lightweight_payload(self, owner_client, product):
        response = owner_client.get('/api/products/lookup/')
        data = assert_ok(response)
        assert len(data) >= 1
        first = data[0]
        # Lookup must include price and stock for order form use
        assert 'id' in first
        assert 'sn' in first
        assert 'price' in first
        assert 'stock' in first
        # Must NOT include heavy fields
        assert 'create_time' not in first
        assert 'category' not in first

    def test_lookup_exclude_out_of_stock(self, owner_client, product, zero_stock_product):
        response = owner_client.get('/api/products/lookup/?exclude_out_of_stock=true')
        data = assert_ok(response)
        ids = [p['id'] for p in data]
        assert zero_stock_product.id not in ids
        assert product.id in ids
