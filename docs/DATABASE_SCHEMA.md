# Database Schema

This document describes every table in the `db_market` database, the relationships between them, and the business rules each table enforces.

**Database:** MySQL 8.0  
**Character set:** utf8mb4 / utf8mb4_unicode_ci  
**Django model:** `AUTH_USER_MODEL = 'user.User'`

---

## Table of Contents

1. [Entity Relationship Overview](#1-entity-relationship-overview)
2. [Table Reference](#2-table-reference)
   - [users](#users)
   - [categories](#categories)
   - [products](#products)
   - [stalls](#stalls)
   - [customer](#customer)
   - [inorder](#inorder)
   - [inorder_products](#inorder_products)
   - [outorder](#outorder)
   - [outorder_products](#outorder_products)
   - [favorites](#favorites)
   - [chat_messages](#chat_messages)
   - [Django system tables](#django-system-tables)
3. [Key Relationships](#3-key-relationships)
4. [Stock Management Rules](#4-stock-management-rules)
5. [Seed Data Summary](#5-seed-data-summary)

---

## 1. Entity Relationship Overview

```
users ──────────────────────────────────────────────────────┐
  │                                                          │
  ├── stalls (owner_id)                                      │
  │                                                          │
  ├── inorder (user_id / operator)                           │
  │     └── inorder_products (inorder_id, product_id) ──┐   │
  │                                                      │   │
  ├── outorder (user_id / operator)                      │   │
  │     └── outorder_products (outorder_id, product_id) ─┤   │
  │                                                      │   │
  ├── favorites (user_id, product_id) ───────────────────┤   │
  │                                                      │   │
  └── chat_messages (sender_id, receiver_id) ────────────┘───┘
                                                         │
customer ──────────────────────────────────────┐         │
  ├── inorder (customer_id / supplier)          │    products (category_id)
  └── outorder (customer_id / buyer)            │         │
                                                │    categories
                                                └─────────┘
```

---

## 2. Table Reference

---

### `users`

Stores all system accounts. The `role` field controls what each user can access.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | INT | PK, AUTO_INCREMENT | User ID |
| `username` | VARCHAR(50) | UNIQUE, NOT NULL | Login username (lowercase) |
| `password` | VARCHAR(128) | NOT NULL | PBKDF2-hashed password |
| `name` | VARCHAR(50) | NOT NULL | Display / real name |
| `role` | ENUM | NOT NULL, DEFAULT 'customer' | `admin` \| `stall_owner` \| `customer` |
| `is_active` | TINYINT(1) | DEFAULT 1 | 1 = active, 0 = disabled |
| `is_deleted` | TINYINT(1) | DEFAULT 0 | Soft delete flag |
| `create_time` | DATETIME | DEFAULT CURRENT_TIMESTAMP | Account creation time |
| `modify_time` | DATETIME | ON UPDATE CURRENT_TIMESTAMP | Last modification time |

**Role permissions:**

| Role | Can do |
|---|---|
| `admin` | Manage users, stalls, all orders, all data |
| `stall_owner` | Manage products, categories, orders, contacts |
| `customer` | Browse products, manage favourites, use chat |

**Notes:**
- Soft delete: setting `is_deleted = 1` hides the user from the default Django manager. Use `User.all_objects` to query deleted users.
- `is_deleted` does not cascade — linked orders remain intact after soft delete.

---

### `categories`

Product classification used for filtering in the inventory view.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | INT | PK, AUTO_INCREMENT | Category ID |
| `name` | VARCHAR(50) | UNIQUE, NOT NULL | Display name (e.g. "Clothing") |
| `description` | VARCHAR(255) | NULL | Optional description |
| `create_time` | DATETIME | DEFAULT CURRENT_TIMESTAMP | — |
| `modify_time` | DATETIME | ON UPDATE CURRENT_TIMESTAMP | — |

**Notes:**
- Cannot be deleted while products are assigned (`ON DELETE RESTRICT` on `products.category_id`).
- Seed data: Clothing, Electronics, Food & Beverages, Home Essentials, Books & Media, Other.

---

### `products`

Central inventory table. Stock is updated automatically by order signals — never written directly.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | INT | PK, AUTO_INCREMENT | Product ID |
| `sn` | VARCHAR(50) | UNIQUE, NOT NULL | Stock number (e.g. CLT-001) |
| `name` | VARCHAR(100) | NOT NULL | Product display name |
| `price` | DECIMAL(10,2) | NOT NULL | Selling price per unit |
| `category_id` | INT | FK → categories.id, RESTRICT | Product category |
| `stock` | INT | DEFAULT 0 | Current on-hand quantity |
| `description` | VARCHAR(255) | NULL | Short description |
| `create_time` | DATETIME | DEFAULT CURRENT_TIMESTAMP | — |
| `modify_time` | DATETIME | ON UPDATE CURRENT_TIMESTAMP | — |

**Stock rules:**
- Stock is **increased** when an inbound order is completed (+amount per line).
- Stock is **decreased** when an outbound order is completed (-amount per line).
- Stock is **restored** when a completed outbound order is cancelled (+amount per line).
- Stock can **never go below 0** — `adjust_stock()` enforces this.
- Direct writes to `stock` via the REST API are **blocked** on the PATCH endpoint.

**Low-stock threshold:** `stock < 20` triggers the low-stock flag and row highlighting.

---

### `stalls`

Represents a market stall operated by a stall_owner user.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | INT | PK, AUTO_INCREMENT | Stall ID |
| `name` | VARCHAR(100) | NOT NULL | Stall display name |
| `owner_id` | INT | FK → users.id, CASCADE | Stall owner (role = stall_owner) |
| `description` | VARCHAR(255) | NULL | Optional stall description |
| `status` | ENUM | DEFAULT 'active' | `active` \| `inactive` \| `suspended` |
| `create_time` | DATETIME | DEFAULT CURRENT_TIMESTAMP | — |
| `modify_time` | DATETIME | ON UPDATE CURRENT_TIMESTAMP | — |

**Status transitions:**

```
active ←─────────────────┐
  │                       │ admin only
  ▼                       │
inactive ──── suspend ──► suspended
```

- Only an admin can move a stall out of `suspended` status.
- A stall owner can activate/deactivate their own stall.

---

### `customer`

External business contacts — either suppliers (for purchasing) or buyers (for sales). Completely separate from the `users` table.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | INT | PK, AUTO_INCREMENT | Contact ID |
| `name` | VARCHAR(50) | NOT NULL | Contact name |
| `phone` | VARCHAR(20) | NOT NULL | Phone number |
| `address` | VARCHAR(128) | NOT NULL | Business address |
| `customer_type` | ENUM | DEFAULT 'buyer' | `supplier` \| `buyer` |
| `create_time` | DATETIME | DEFAULT CURRENT_TIMESTAMP | — |
| `modify_time` | DATETIME | ON UPDATE CURRENT_TIMESTAMP | — |

**Notes:**
- `supplier` — referenced by `inorder.customer_id` (purchase orders).
- `buyer` — referenced by `outorder.customer_id` (sales orders).
- Cannot be deleted while linked orders exist (enforced at application layer).

---

### `inorder`

Inbound (purchase) order header. One record per purchase transaction.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | INT | PK, AUTO_INCREMENT | Order ID |
| `code` | VARCHAR(50) | UNIQUE, NOT NULL | Order code (e.g. IN2024112701) |
| `customer_id` | INT | FK → customer.id, CASCADE | Supplier for this purchase |
| `user_id` | INT | FK → users.id, CASCADE | Operator who created the order |
| `status` | ENUM | DEFAULT 'draft' | `draft` \| `completed` \| `cancelled` |
| `remark` | VARCHAR(255) | NULL | Optional notes |
| `create_time` | DATETIME | DEFAULT CURRENT_TIMESTAMP | — |
| `modify_time` | DATETIME | ON UPDATE CURRENT_TIMESTAMP | — |

**Status rules:**
- `draft` → editable (lines can be added/removed, header can be updated).
- `draft → completed` → stock increases for all line items (via signal).
- `draft → cancelled` → no stock change.
- Completed and cancelled orders are **immutable**.

---

### `inorder_products`

Line items for an inbound order. One row per product per order.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | INT | PK, AUTO_INCREMENT | Line ID |
| `inorder_id` | INT | FK → inorder.id, CASCADE | Parent order |
| `product_id` | INT | FK → products.id, CASCADE | Product being purchased |
| `amount` | INT | NOT NULL, DEFAULT 0 | Quantity ordered |
| `unit_price` | DECIMAL(10,2) | NULL | Purchase price paid to supplier |

**Notes:**
- Deleted automatically when the parent `inorder` is deleted (CASCADE).
- `amount` must be ≥ 1 (enforced at application layer).
- `unit_price` is optional — can be filled in later.

---

### `outorder`

Outbound (sales) order header. One record per sale transaction.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | INT | PK, AUTO_INCREMENT | Order ID |
| `code` | VARCHAR(50) | UNIQUE, NOT NULL | Order code (e.g. OUT2024112701) |
| `customer_id` | INT | FK → customer.id, CASCADE | Buyer for this sale |
| `user_id` | INT | FK → users.id, CASCADE | Operator who created the order |
| `status` | ENUM | DEFAULT 'draft' | `draft` \| `completed` \| `cancelled` |
| `remark` | VARCHAR(255) | NULL | Optional notes |
| `create_time` | DATETIME | DEFAULT CURRENT_TIMESTAMP | — |
| `modify_time` | DATETIME | ON UPDATE CURRENT_TIMESTAMP | — |

**Status rules:**
- `draft → completed` → stock sufficiency check + stock deduction (atomic).
- `draft → cancelled` → no stock change.
- `completed → cancelled` → **stock is restored** (admin only).
- If stock is insufficient for any line, the entire completion is rejected and no stock is changed.

---

### `outorder_products`

Line items for an outbound order. One row per product per order.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | INT | PK, AUTO_INCREMENT | Line ID |
| `outorder_id` | INT | FK → outorder.id, CASCADE | Parent order |
| `product_id` | INT | FK → products.id, CASCADE | Product being sold |
| `amount` | INT | NOT NULL, DEFAULT 0 | Quantity sold |
| `unit_price` | DECIMAL(10,2) | NULL | Selling price charged to buyer |

---

### `favorites`

Bookmarks: one row per user–product pair.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | INT | PK, AUTO_INCREMENT | Favourite ID |
| `user_id` | INT | FK → users.id, CASCADE | The user |
| `product_id` | INT | FK → products.id, CASCADE | The favourited product |
| `create_time` | DATETIME | DEFAULT CURRENT_TIMESTAMP | When it was favourited |

**Unique constraint:** `UNIQUE KEY unique_user_product (user_id, product_id)` — a user cannot favourite the same product twice.

**Notes:**
- Toggled by a single POST to `/api/favorites/toggle/<product_id>/`.
- Deleted automatically if the user or product is deleted (CASCADE).

---

### `chat_messages`

Direct messages between two users (customer ↔ stall_owner).

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | INT | PK, AUTO_INCREMENT | Message ID |
| `sender_id` | INT | FK → users.id, CASCADE | Message author |
| `receiver_id` | INT | FK → users.id, CASCADE | Intended recipient |
| `content` | TEXT | NOT NULL | Message body (max 5000 chars) |
| `is_read` | TINYINT(1) | DEFAULT 0 | 0 = unread, 1 = read |
| `create_time` | DATETIME | DEFAULT CURRENT_TIMESTAMP | Sent time |

**Notes:**
- Messages are immutable once sent (content cannot be edited).
- `is_read` is set to `1` when the receiver fetches the conversation history or connects via WebSocket.
- Real-time delivery via Django Channels WebSocket (`ws://host/ws/chat/<other_user_id>/`).
- Valid chat pairs: `customer ↔ stall_owner`, `admin ↔ anyone`. Customers cannot message other customers.

---

### Django system tables

These tables are created and managed automatically by Django. Do not modify them manually.

| Table | Purpose |
|---|---|
| `django_content_type` | Maps app/model names for the permission system |
| `auth_permission` | Granular model-level permissions |
| `auth_group` | Role groups (admin, stall_owner, customer) |
| `auth_group_permissions` | Maps permissions to groups |
| `django_session` | User sessions (used by session authentication) |
| `authtoken_token` | DRF authentication tokens (one per user) |
| `django_migrations` | Tracks which migrations have been applied |
| `django_admin_log` | Records of admin panel actions |

---

## 3. Key Relationships

```
users (1) ──────────────── (N) stalls
users (1) ──────────────── (N) inorder        [as operator]
users (1) ──────────────── (N) outorder       [as operator]
users (1) ──────────────── (N) favorites
users (1) ──────────────── (N) chat_messages  [as sender]
users (1) ──────────────── (N) chat_messages  [as receiver]

customer (1) ────────────── (N) inorder       [customer_type=supplier]
customer (1) ────────────── (N) outorder      [customer_type=buyer]

categories (1) ──────────── (N) products

products (1) ────────────── (N) inorder_products
products (1) ────────────── (N) outorder_products
products (1) ────────────── (N) favorites

inorder (1) ─────────────── (N) inorder_products
outorder (1) ────────────── (N) outorder_products
```

---

## 4. Stock Management Rules

Stock changes always go through `utils.helpers.adjust_stock()` which uses `SELECT FOR UPDATE` inside `transaction.atomic()`.

| Event | Direction | Who triggers it |
|---|---|---|
| Inbound order completed | + amount per line | `inorder/signals.py` |
| Outbound order completed | - amount per line | `outorder/signals.py` |
| Outbound order cancelled (from completed) | + amount per line | `outorder/signals.py` |

**Race condition protection:** When two simultaneous outbound orders try to purchase the same product, `SELECT FOR UPDATE` locks the product row. The second transaction waits until the first commits, then re-checks the stock value. If insufficient stock remains, it rolls back with a clear error.

---

## 5. Seed Data Summary

The `db_market.sql` file inserts the following sample data:

**Users (password for all: `123456`)**

| Username | Name | Role |
|---|---|---|
| admin | Admin Zhang | admin |
| owner1 | Stall Owner Li | stall_owner |
| customer1 | Customer Wang | customer |

**Categories:** Clothing, Electronics, Food & Beverages, Home Essentials, Books & Media, Other

**Products:** 15 products across all categories (CLT-001 through BOOK-002)

**Stalls:** 1 stall — "Li Stall General Store" (owned by owner1)

**Customers (contacts):**

| Name | Type |
|---|---|
| Supplier A | supplier |
| Supplier B | supplier |
| Buyer C | buyer |

**Orders:** 2 completed inbound orders + 2 completed outbound orders

**Favourites:** customer1 has favourited products 1, 5, 9

**Chat messages:** 3 messages between customer1 and owner1
