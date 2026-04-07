"""
tests/test_inorder.py
=====================
Tests for the InOrder model, signals, and REST API.

Coverage
--------
- InOrder model: status helpers, is_editable, computed totals
- Create order with lines (draft)
- Retrieve order with nested line details
- Update draft order (header + replace lines)
- Immutability: completed/cancelled orders cannot be edited
- Complete order: stock increases by ordered quantity (signal)
- Cancel order: no stock change from draft
- Delete draft order: hard delete + line CASCADE
- Cannot delete completed order
- Permission checks
- Signal idempotency: completing an already-completed order does not double-adjust stock
"""

import pytest
from apps.inorder.models import InOrder, InOrderProduct
from apps.product.models import Product
from tests.conftest import assert_ok, assert_fail

pytestmark = pytest.mark.django_db


# ===========================================================================
# InOrder model unit tests
# ===========================================================================
class TestInOrderModel:

    def test_status_helpers(self, draft_inorder):
        assert draft_inorder.is_draft      is True
        assert draft_inorder.is_completed  is False
        assert draft_inorder.is_cancelled  is False
        assert draft_inorder.is_editable   is True

    def test_total_amount(self, draft_inorder):
        # Fixture creates one line: product × 50
        assert draft_inorder.total_amount == 50

    def test_total_value(self, draft_inorder):
        # 50 × 50.00
        assert draft_inorder.total_value == pytest.approx(2500.00, rel=1e-4)

    def test_completed_order_is_not_editable(self, draft_inorder):
        draft_inorder._previous_status = draft_inorder.status
        draft_inorder.status = InOrder.Status.COMPLETED
        draft_inorder.save()
        assert draft_inorder.is_editable is False

    def test_str_representation(self, draft_inorder):
        assert 'IN20241201001' in str(draft_inorder)
        assert 'Draft' in str(draft_inorder)


# ===========================================================================
# InOrder API: Create
# ===========================================================================
class TestInOrderCreate:

    def test_owner_can_create_draft_order(self, owner_client, supplier, product):
        response = owner_client.post('/api/inorders/', {
            'code':        'IN20250101001',
            'customer_id': supplier.id,
            'remark':      'Test order',
            'lines': [
                {'product_id': product.id, 'amount': 30, 'unit_price': '45.00'},
            ],
        }, format='json')
        data = assert_ok(response, code=201)
        assert data['code'] == 'IN20250101001'
        assert data['status'] == 'draft'
        assert len(data['lines']) == 1
        assert data['lines'][0]['amount'] == 30

    def test_create_order_with_buyer_fails(self, owner_client, buyer, product):
        """Inbound orders require a SUPPLIER, not a buyer."""
        response = owner_client.post('/api/inorders/', {
            'code':        'IN20250101002',
            'customer_id': buyer.id,
            'lines': [{'product_id': product.id, 'amount': 5}],
        }, format='json')
        assert_fail(response, code=400)

    def test_create_order_empty_lines_fails(self, owner_client, supplier):
        response = owner_client.post('/api/inorders/', {
            'code':        'IN20250101003',
            'customer_id': supplier.id,
            'lines':       [],
        }, format='json')
        assert_fail(response, code=400)

    def test_create_order_duplicate_code_fails(self, owner_client, supplier, product, draft_inorder):
        response = owner_client.post('/api/inorders/', {
            'code':        'IN20241201001',   # already exists from fixture
            'customer_id': supplier.id,
            'lines': [{'product_id': product.id, 'amount': 1}],
        }, format='json')
        assert_fail(response, code=400)

    def test_create_order_duplicate_product_in_lines_fails(self, owner_client, supplier, product):
        response = owner_client.post('/api/inorders/', {
            'code':        'IN20250101004',
            'customer_id': supplier.id,
            'lines': [
                {'product_id': product.id, 'amount': 10},
                {'product_id': product.id, 'amount': 20},  # duplicate
            ],
        }, format='json')
        assert_fail(response, code=400)

    def test_customer_cannot_create_order(self, customer_client, supplier, product):
        response = customer_client.post('/api/inorders/', {
            'code':        'IN20250101005',
            'customer_id': supplier.id,
            'lines': [{'product_id': product.id, 'amount': 1}],
        }, format='json')
        assert response.status_code == 403


# ===========================================================================
# InOrder API: Retrieve and Update
# ===========================================================================
class TestInOrderRetrieveUpdate:

    def test_retrieve_order_has_nested_lines(self, owner_client, draft_inorder):
        response = owner_client.get(f'/api/inorders/{draft_inorder.id}/')
        data = assert_ok(response)
        assert data['code'] == 'IN20241201001'
        assert len(data['lines']) == 1
        assert data['lines'][0]['product']['sn'] == 'CLT-001'

    def test_update_draft_order_remark(self, owner_client, draft_inorder):
        response = owner_client.patch(f'/api/inorders/{draft_inorder.id}/', {
            'remark': 'Updated remark',
        }, format='json')
        data = assert_ok(response)
        assert data['remark'] == 'Updated remark'

    def test_update_draft_replaces_lines(self, owner_client, draft_inorder, product, category, db):
        new_product = Product.objects.create(
            sn='NEW-002', name='New Product', price='20', category=category, stock=50
        )
        response = owner_client.patch(f'/api/inorders/{draft_inorder.id}/', {
            'lines': [
                {'product_id': new_product.id, 'amount': 25, 'unit_price': '18.00'}
            ],
        }, format='json')
        data = assert_ok(response)
        assert len(data['lines']) == 1
        assert data['lines'][0]['product']['id'] == new_product.id
        assert data['lines'][0]['amount'] == 25

    def test_cannot_edit_completed_order(self, owner_client, draft_inorder):
        # Complete the order first
        draft_inorder._previous_status = draft_inorder.status
        draft_inorder.status = InOrder.Status.COMPLETED
        draft_inorder.save()

        response = owner_client.patch(f'/api/inorders/{draft_inorder.id}/', {
            'remark': 'Should fail',
        }, format='json')
        assert_fail(response, code=400)

    def test_status_change_via_patch_is_rejected(self, owner_client, draft_inorder):
        response = owner_client.patch(f'/api/inorders/{draft_inorder.id}/', {
            'status': 'completed',
        }, format='json')
        assert_fail(response, code=400)


# ===========================================================================
# InOrder API: Complete (stock increase via signal)
# ===========================================================================
class TestInOrderComplete:

    def test_complete_order_increases_stock(self, owner_client, draft_inorder, product):
        initial_stock = product.stock   # 100
        response = owner_client.post(f'/api/inorders/{draft_inorder.id}/complete/')
        assert_ok(response)

        product.refresh_from_db()
        # Stock should have increased by the ordered amount (50)
        assert product.stock == initial_stock + 50

    def test_complete_changes_status_to_completed(self, owner_client, draft_inorder):
        owner_client.post(f'/api/inorders/{draft_inorder.id}/complete/')
        draft_inorder.refresh_from_db()
        assert draft_inorder.status == InOrder.Status.COMPLETED

    def test_cannot_complete_already_completed_order(self, owner_client, draft_inorder):
        # Complete once
        owner_client.post(f'/api/inorders/{draft_inorder.id}/complete/')
        # Try to complete again
        response = owner_client.post(f'/api/inorders/{draft_inorder.id}/complete/')
        assert_fail(response, code=400)

    def test_cannot_complete_cancelled_order(self, owner_client, draft_inorder):
        owner_client.post(f'/api/inorders/{draft_inorder.id}/cancel/')
        response = owner_client.post(f'/api/inorders/{draft_inorder.id}/complete/')
        assert_fail(response, code=400)

    def test_complete_order_without_lines_fails(self, owner_client, supplier, stall_owner_user):
        empty_order = InOrder.objects.create(
            code='INEMPTY001',
            customer=supplier,
            operator=stall_owner_user,
            status='draft',
        )
        response = owner_client.post(f'/api/inorders/{empty_order.id}/complete/')
        assert_fail(response, code=400)

    def test_signal_idempotency_no_double_stock_increase(self, owner_client, draft_inorder, product):
        """Saving a completed order again must NOT increase stock a second time."""
        initial_stock = product.stock
        # Complete the order (stock increases by 50)
        owner_client.post(f'/api/inorders/{draft_inorder.id}/complete/')

        # Re-save without changing status (simulates an admin saving in the admin panel)
        draft_inorder.refresh_from_db()
        draft_inorder.save()   # no _previous_status set → signal skips

        product.refresh_from_db()
        # Stock must only have increased ONCE
        assert product.stock == initial_stock + 50


# ===========================================================================
# InOrder API: Cancel
# ===========================================================================
class TestInOrderCancel:

    def test_cancel_draft_order_no_stock_change(self, owner_client, draft_inorder, product):
        initial_stock = product.stock
        response = owner_client.post(f'/api/inorders/{draft_inorder.id}/cancel/')
        assert_ok(response)

        product.refresh_from_db()
        assert product.stock == initial_stock   # unchanged

    def test_cancel_changes_status(self, owner_client, draft_inorder):
        owner_client.post(f'/api/inorders/{draft_inorder.id}/cancel/')
        draft_inorder.refresh_from_db()
        assert draft_inorder.status == InOrder.Status.CANCELLED

    def test_cannot_cancel_already_cancelled(self, owner_client, draft_inorder):
        owner_client.post(f'/api/inorders/{draft_inorder.id}/cancel/')
        response = owner_client.post(f'/api/inorders/{draft_inorder.id}/cancel/')
        assert_fail(response, code=400)


# ===========================================================================
# InOrder API: Delete
# ===========================================================================
class TestInOrderDelete:

    def test_delete_draft_order(self, owner_client, draft_inorder):
        order_id = draft_inorder.id
        response = owner_client.delete(f'/api/inorders/{order_id}/delete/')
        assert_ok(response)
        assert not InOrder.objects.filter(pk=order_id).exists()
        # Lines must also be deleted (CASCADE)
        assert not InOrderProduct.objects.filter(inorder_id=order_id).exists()

    def test_cannot_delete_completed_order(self, owner_client, draft_inorder):
        draft_inorder._previous_status = draft_inorder.status
        draft_inorder.status = InOrder.Status.COMPLETED
        draft_inorder.save()
        response = owner_client.delete(f'/api/inorders/{draft_inorder.id}/delete/')
        assert_fail(response, code=400)

    def test_cannot_delete_cancelled_order(self, owner_client, draft_inorder):
        owner_client.post(f'/api/inorders/{draft_inorder.id}/cancel/')
        response = owner_client.delete(f'/api/inorders/{draft_inorder.id}/delete/')
        assert_fail(response, code=400)
