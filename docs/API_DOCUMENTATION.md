# API Documentation

Complete reference for the StallManagement REST API.

**Base URL:** `http://127.0.0.1:8000`  
**Format:** All requests and responses use `application/json`.  
**Authentication:** DRF Token or Django Session (set on login).

---

## Table of Contents

1. [Response Envelope](#1-response-envelope)
2. [Authentication](#2-authentication)
3. [Users](#3-users)
4. [Customers (Contacts)](#4-customers-contacts)
5. [Categories](#5-categories)
6. [Products](#6-products)
7. [Stalls](#7-stalls)
8. [Inbound Orders](#8-inbound-orders)
9. [Outbound Orders](#9-outbound-orders)
10. [Favourites](#10-favourites)
11. [Chat](#11-chat)
12. [WebSocket](#12-websocket)
13. [Error Reference](#13-error-reference)

---

## 1. Response Envelope

Every API response — success or failure — uses this consistent JSON shape:

```json
{
    "success": true,
    "code":    200,
    "message": "Human-readable description",
    "data":    { }
}
```

| Field | Type | Description |
|---|---|---|
| `success` | boolean | `true` = request succeeded, `false` = request failed |
| `code` | integer | HTTP status code (mirrors the HTTP response status) |
| `message` | string | Plain-English description of the result |
| `data` | object / array / null | The response payload; `null` on simple success or error |

---

## 2. Authentication

### Login
`POST /api/auth/login/`  
**Permission:** Public

**Request body:**
```json
{
    "username": "owner1",
    "password": "123456"
}
```

**Success response (200):**
```json
{
    "success": true,
    "code":    200,
    "message": "Login successful.",
    "data": {
        "token": "9944b09199c62bcf9418ad846dd0e4bbdfc6ee4b",
        "user": {
            "id":       2,
            "username": "owner1",
            "name":     "Stall Owner Li",
            "role":     "stall_owner"
        }
    }
}
```

Use the token in all subsequent requests:
```
Authorization: Token 9944b09199c62bcf9418ad846dd0e4bbdfc6ee4b
```

---

### Logout
`POST /api/auth/logout/`  
**Permission:** Authenticated

Invalidates the token and clears the session.

**Success response (200):**
```json
{
    "success": true,
    "code":    200,
    "message": "Logged out successfully.",
    "data":    null
}
```

---

### Current user profile
`GET /api/auth/me/`  
**Permission:** Authenticated

Returns the authenticated user's profile. Used to restore login state after page reload.

**Success response (200):**
```json
{
    "success": true,
    "data": {
        "id":          2,
        "username":    "owner1",
        "name":        "Stall Owner Li",
        "role":        "stall_owner",
        "is_active":   true,
        "create_time": "2024-11-27T10:00:00Z"
    }
}
```

---

## 3. Users

**Base path:** `/api/users/`  
**Permission:** Admin only (except `change_password`)

---

### List users
`GET /api/users/`

**Query parameters:**

| Parameter | Type | Description |
|---|---|---|
| `role` | string | Filter by role: `admin` \| `stall_owner` \| `customer` |
| `is_active` | boolean | Filter by active status: `true` \| `false` |
| `search` | string | Search username or name |
| `page` | integer | Page number (default: 1) |
| `page_size` | integer | Items per page (default: 20, max: 100) |

**Success response (200):**
```json
{
    "success": true,
    "data": {
        "total":     3,
        "page":      1,
        "page_size": 20,
        "results": [
            {
                "id":          1,
                "username":    "admin",
                "name":        "Admin Zhang",
                "role":        "admin",
                "role_display":"Admin",
                "is_active":   true,
                "create_time": "2024-11-27T10:00:00Z",
                "modify_time": "2024-11-27T10:00:00Z"
            }
        ]
    }
}
```

---

### Create user
`POST /api/users/`

**Request body:**
```json
{
    "username":         "newuser",
    "password":         "SecurePass123!",
    "password_confirm": "SecurePass123!",
    "name":             "New User",
    "role":             "customer",
    "is_active":        true
}
```

**Success response (201):** Returns the created user object.

---

### Retrieve user
`GET /api/users/<id>/`

---

### Update user
`PATCH /api/users/<id>/`

All fields optional. Omit `password` to keep it unchanged.

```json
{
    "name":     "Updated Name",
    "role":     "stall_owner",
    "is_active": false
}
```

---

### Soft-delete user
`DELETE /api/users/<id>/delete/`

Sets `is_deleted = true`. The user is hidden from queries but data is preserved.

---

### Restore soft-deleted user
`POST /api/users/<id>/restore/`

---

### Change password
`POST /api/users/change_password/`  
**Permission:** Any authenticated user (for their own password)

```json
{
    "current_password":     "OldPass123!",
    "new_password":         "NewPass456!",
    "new_password_confirm": "NewPass456!"
}
```

Returns a new auth token (old token is invalidated).

---

## 4. Customers (Contacts)

**Base path:** `/api/customers/`  
**Permission:** Admin + Stall Owner

These are external business contacts (suppliers and buyers), not system user accounts.

---

### List contacts
`GET /api/customers/`

| Parameter | Type | Description |
|---|---|---|
| `customer_type` | string | `supplier` \| `buyer` |
| `search` | string | Search name, phone, address |
| `ordering` | string | `name` \| `-name` \| `customer_type` \| `create_time` |
| `page` / `page_size` | integer | Pagination |

---

### Create contact
`POST /api/customers/`

```json
{
    "name":          "New Supplier",
    "phone":         "13800000099",
    "address":       "Jurong West",
    "customer_type": "supplier"
}
```

---

### Retrieve contact
`GET /api/customers/<id>/`

Response includes `inbound_order_count` and `outbound_order_count`.

---

### Update contact
`PATCH /api/customers/<id>/`

Changing `customer_type` from supplier to buyer is blocked if the contact has existing inbound orders (and vice versa).

---

### Delete contact
`DELETE /api/customers/<id>/delete/`

Blocked if the contact has any linked orders.

---

### List contact type choices
`GET /api/customers/types/`

Returns `[{ "value": "supplier", "label": "Supplier" }, ...]`

---

## 5. Categories

**Base path:** `/api/categories/`  
**Permission:** GET — any authenticated user. Write — Admin + Stall Owner.

---

### List categories
`GET /api/categories/`

| Parameter | Type | Description |
|---|---|---|
| `search` | string | Search name and description |
| `ordering` | string | `name` \| `-name` \| `create_time` |
| `with_count` | boolean | Include `product_count` (default: `true`) |

---

### Create category
`POST /api/categories/`

```json
{
    "name":        "New Category",
    "description": "Optional description"
}
```

Names are auto-converted to title case.

---

### Retrieve / Update / Delete
- `GET /api/categories/<id>/`
- `PATCH /api/categories/<id>/`
- `DELETE /api/categories/<id>/delete/` — blocked if products are assigned.

---

### Lookup (lightweight list for dropdowns)
`GET /api/categories/lookup/`

Returns `[{ "id": 1, "name": "Clothing" }, ...]` — no timestamps or counts.

---

## 6. Products

**Base path:** `/api/products/`  
**Permission:** GET — any authenticated user. Write — Admin + Stall Owner.

---

### List products
`GET /api/products/`

| Parameter | Type | Description |
|---|---|---|
| `search` | string | Search SN, name, description |
| `category_id` | integer | Filter by category |
| `stock_status` | string | `ok` \| `low` \| `out` |
| `price_min` | decimal | Minimum price (inclusive) |
| `price_max` | decimal | Maximum price (inclusive) |
| `ordering` | string | `name` \| `price` \| `stock` \| `create_time` (prefix `-` to reverse) |
| `page` / `page_size` | integer | Pagination |

**Response includes:** `low_stock_threshold` (20) so the frontend does not need to hard-code it.

---

### Create product
`POST /api/products/`

```json
{
    "sn":          "NEW-001",
    "name":        "New Product",
    "price":       "49.99",
    "category_id": 1,
    "stock":       50,
    "description": "Optional description"
}
```

SN is auto-converted to uppercase. Stock defaults to 0 if omitted.

---

### Retrieve product
`GET /api/products/<id>/`

Response includes nested category `{ id, name }` and computed fields `is_low_stock`, `is_out_of_stock`, `stock_status`.

---

### Update product
`PATCH /api/products/<id>/`

Updating `stock` directly is **blocked** — use orders instead.

---

### Delete product
`DELETE /api/products/<id>/delete/`

Blocked if the product appears in any order line. Response includes `inbound_order_line_count` and `outbound_order_line_count`.

---

### Low-stock list
`GET /api/products/low_stock/`  
**Permission:** Admin + Stall Owner

Returns all products with `stock < 20`. Supports the same filter/pagination params as the main list.

---

### Lookup (for order form dropdowns)
`GET /api/products/lookup/`  
**Permission:** Admin + Stall Owner

Returns `[{ id, sn, name, price, stock }]`. Pass `exclude_out_of_stock=true` to hide products with zero stock.

---

## 7. Stalls

**Base path:** `/api/stalls/`  
**Permission:** Admin + Stall Owner (owners see only their own stall)

---

### List stalls
`GET /api/stalls/`

Stall owners automatically see only their own stall(s). Admins see all.

| Parameter | Description |
|---|---|
| `status` | `active` \| `inactive` \| `suspended` |
| `search` | Search name and description |
| `owner_id` | Admin only — filter by owner user ID |

---

### Create stall
`POST /api/stalls/`  
**Permission:** Admin only

```json
{
    "name":        "New Stall",
    "owner_id":    2,
    "description": "A new market stall",
    "status":      "active"
}
```

`owner_id` must reference a user with `role = stall_owner`.

---

### Retrieve / Update
- `GET /api/stalls/<id>/`
- `PATCH /api/stalls/<id>/` — Admin only. Cannot change status via PATCH; use action endpoints.

---

### Status actions

| Endpoint | Method | Permission | Result |
|---|---|---|---|
| `/api/stalls/<id>/activate/` | POST | Admin + own stall_owner | Status → `active` |
| `/api/stalls/<id>/deactivate/` | POST | Admin + own stall_owner | Status → `inactive` |
| `/api/stalls/<id>/suspend/` | POST | Admin only | Status → `suspended` |

Stall owners cannot unsuspend a stall — only admins can.

---

### Status choices lookup
`GET /api/stalls/status_choices/`

Returns `[{ "value": "active", "label": "Active" }, ...]`

---

## 8. Inbound Orders

**Base path:** `/api/inorders/`  
**Permission:** Admin + Stall Owner

---

### List orders
`GET /api/inorders/`

| Parameter | Description |
|---|---|
| `status` | `draft` \| `completed` \| `cancelled` |
| `customer_id` | Filter by supplier ID |
| `search` | Search order code and remark |
| `ordering` | `code` \| `-code` \| `create_time` \| `-create_time` |

---

### Create order
`POST /api/inorders/`

```json
{
    "code":        "IN20241201001",
    "customer_id": 1,
    "remark":      "Optional note",
    "lines": [
        { "product_id": 1, "amount": 50, "unit_price": "50.00" },
        { "product_id": 5, "amount": 30, "unit_price": "250.00" }
    ]
}
```

- `customer_id` must reference a contact with `customer_type = supplier`.
- At least one line is required.
- Each product may appear only once per order.
- Order is created in `draft` status.

---

### Retrieve / Update
- `GET /api/inorders/<id>/` — includes nested lines with product details.
- `PATCH /api/inorders/<id>/` — draft orders only. If `lines` is provided, the entire lines list is replaced.

---

### Status actions

| Endpoint | Result | Stock change |
|---|---|---|
| `POST /api/inorders/<id>/complete/` | `draft → completed` | +amount per line |
| `POST /api/inorders/<id>/cancel/` | `draft → cancelled` | None |

---

### Delete
`DELETE /api/inorders/<id>/delete/`

Draft orders only. Lines are deleted automatically (CASCADE).

---

## 9. Outbound Orders

**Base path:** `/api/outorders/`  
**Permission:** Admin + Stall Owner

---

### Create order
`POST /api/outorders/`

```json
{
    "code":        "OUT20241201001",
    "customer_id": 3,
    "remark":      "Urgent delivery",
    "lines": [
        { "product_id": 1, "amount": 20, "unit_price": "59.99" },
        { "product_id": 2, "amount": 15, "unit_price": "129.99" }
    ]
}
```

- `customer_id` must reference a contact with `customer_type = buyer`.
- Creating a draft order does **not** change stock.

---

### Complete order
`POST /api/outorders/<id>/complete/`

Inside `transaction.atomic()`:
1. Locks product rows with `SELECT FOR UPDATE`.
2. Verifies stock is sufficient for every line.
3. If any line fails, rejects the entire request — no partial deductions.
4. On success, deducts stock for all lines via signal.

**Insufficient stock response (400):**
```json
{
    "success": false,
    "code":    400,
    "message": "Insufficient stock for one or more products.",
    "data": [
        {
            "product_id":   1,
            "product_sn":   "CLT-001",
            "product_name": "Men's T-Shirt",
            "stock":        5,
            "requested":    20,
            "shortfall":    15
        }
    ]
}
```

---

### Cancel order

| From status | Permission | Stock change |
|---|---|---|
| `draft → cancelled` | Admin + Stall Owner | None |
| `completed → cancelled` | **Admin only** | +amount per line (restored) |

---

## 10. Favourites

**Base path:** `/api/favorites/`  
**Permission:** Any authenticated user (own data only)

---

### List own favourites
`GET /api/favorites/`

| Parameter | Description |
|---|---|
| `search` | Search product name, SN, description |
| `category_id` | Filter by product category |
| `stock_status` | `ok` \| `low` \| `out` |

**Response includes** full product snapshot with stock status and category name.

---

### Toggle favourite
`POST /api/favorites/toggle/<product_id>/`

- Not favourited → adds it (returns `201`, `action: "added"`)
- Already favourited → removes it (returns `200`, `action: "removed"`)

```json
{
    "success": true,
    "data": {
        "action":       "added",
        "is_favourite": true,
        "product_id":   1,
        "favorite_id":  7
    }
}
```

---

### Check if favourited
`GET /api/favorites/check/<product_id>/`

```json
{
    "success": true,
    "data": {
        "product_id":   1,
        "is_favourite": true,
        "favorite_id":  7
    }
}
```

---

### Clear all favourites
`DELETE /api/favorites/clear/`

```json
{
    "success": true,
    "data": { "removed_count": 3 }
}
```

---

## 11. Chat

**Base path:** `/api/chat/`  
**Permission:** Any authenticated user

Valid chat pairs: `customer ↔ stall_owner`, `admin ↔ anyone`. Customers cannot message other customers.

---

### Inbox
`GET /api/chat/inbox/`

Returns all conversations the user is part of, with the last message preview and unread count per partner. Ordered by most recent message first.

```json
{
    "data": {
        "total": 1,
        "results": [
            {
                "partner": { "id": 2, "username": "owner1", "name": "Stall Owner Li", "role": "stall_owner" },
                "last_message": {
                    "id":          3,
                    "content":     "I would like 20 units...",
                    "create_time": "2024-11-27T10:02:00Z",
                    "is_read":     false,
                    "is_mine":     true
                },
                "unread_count": 0
            }
        ]
    }
}
```

---

### Unread count
`GET /api/chat/unread_count/`

Used to render the navigation badge (e.g. "Chat (2)").

```json
{
    "data": { "unread_count": 2 }
}
```

---

### Send message (REST fallback)
`POST /api/chat/send/`

```json
{
    "receiver_id": 2,
    "content":     "Hello, do you have sports pants?"
}
```

Returns the saved message object (201). Under normal operation messages are sent via WebSocket; this endpoint is a reliable fallback if the connection drops.

---

### Conversation history
`GET /api/chat/history/<other_user_id>/`

Returns all messages between the requesting user and the specified partner, in chronological order. Also marks all received messages from the partner as read.

| Parameter | Description |
|---|---|
| `page` | Page number (default: 1) |
| `page_size` | Items per page (default: 50, max: 200) |

---

### Mark as read
`POST /api/chat/mark_read/<other_user_id>/`

Marks all unread messages from `<other_user_id>` to the requesting user as read.

```json
{
    "data": { "marked_count": 3 }
}
```

---

## 12. WebSocket

Real-time message delivery via Django Channels.

**URL:** `ws://127.0.0.1:8000/ws/chat/<other_user_id>/`

The user is authenticated via the Django session cookie (set on login). The browser handles this automatically.

### Connect

```javascript
const ws = new WebSocket('ws://127.0.0.1:8000/ws/chat/2/');
```

On connection, all unread messages from the partner are automatically marked as read.

---

### Send a message

```javascript
ws.send(JSON.stringify({ content: "Hello!" }));
```

---

### Receive a message

```javascript
ws.onmessage = (event) => {
    const frame = JSON.parse(event.data);

    if (frame.type === 'chat_message') {
        const msg = frame.message;
        // msg.sender_id, msg.sender_name, msg.content, msg.create_time
    }

    if (frame.type === 'error') {
        console.error(frame.message);
    }
};
```

---

### Close codes

| Code | Meaning |
|---|---|
| 4001 | Not authenticated (anonymous user) |
| 4002 | Invalid `other_user_id` in URL |
| 4003 | Partner user not found or inactive |

---

## 13. Error Reference

### HTTP status codes

| Code | Meaning |
|---|---|
| 200 | Success |
| 201 | Created |
| 400 | Bad request (validation error, business rule violation) |
| 401 | Unauthenticated — missing or invalid token |
| 403 | Forbidden — authenticated but wrong role |
| 404 | Resource not found |
| 500 | Internal server error |

### Common error responses

**Unauthenticated (401):**
```json
{
    "success": false,
    "code":    401,
    "message": "Authentication credentials were not provided.",
    "data":    null
}
```

**Wrong role (403):**
```json
{
    "success": false,
    "code":    403,
    "message": "Access denied. Admin or Stall Owner role is required.",
    "data":    null
}
```

**Validation error (400):**
```json
{
    "success": false,
    "code":    400,
    "message": "Validation failed.",
    "data": {
        "code": ["An inbound order with code \"IN20241201001\" already exists."]
    }
}
```

**Insufficient stock (400):**
```json
{
    "success": false,
    "code":    400,
    "message": "Insufficient stock for one or more products.",
    "data": [
        {
            "product_id":   1,
            "product_sn":   "CLT-001",
            "product_name": "Men's T-Shirt",
            "stock":        5,
            "requested":    20,
            "shortfall":    15
        }
    ]
}
```
