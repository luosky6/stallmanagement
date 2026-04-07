# StallManagement

A full-stack market stall inventory management system built with **Django 3.2**, **Django REST Framework**, **Django Channels** (WebSocket), and a **Vue 3 SPA** frontend.

## Tech Stack

| Layer | Technology |
|---|---|
| Backend framework | Django 3.2 LTS |
| REST API | Django REST Framework 3.14 |
| Real-time chat | Django Channels 3 + Redis |
| Database | MySQL 8.0 |
| ASGI server | Daphne 3 |
| Frontend | Vue 3 (CDN, single HTML file) |
| Auth | DRF Token + Django Session |
| Python | 3.7+ |

## Project Structure

```
StallManagement/
├── StallManagement/   # Django config (settings, urls, asgi, wsgi)
├── apps/              # Business logic modules
│   ├── user/          # Custom user model (role-based)
│   ├── common/        # Login, logout, SPA entry point
│   ├── customer/      # External contacts (suppliers & buyers)
│   ├── category/      # Product categories
│   ├── product/       # Inventory products
│   ├── stall/         # Stall management
│   ├── inorder/       # Inbound (purchase) orders + stock increase
│   ├── outorder/      # Outbound (sales) orders + stock deduction
│   ├── favorite/      # Product favourites
│   └── chat/          # Real-time chat (WebSocket + REST)
├── api/               # URL routing layer (thin pass-through)
├── utils/             # Shared helpers, constants, validators
├── templates/         # index.html (Vue 3 SPA entry point)
├── tests/             # pytest test suite
└── logs/              # Rotating log files
```

## User Roles

| Role | Access |
|---|---|
| `admin` | Full access — manage users, stalls, all orders |
| `stall_owner` | Manage products, categories, orders, contacts |
| `customer` | Browse products, manage favourites, chat |

## Quick Start

### 1. Prerequisites

- Python 3.7+
- MySQL 8.0 running locally
- Redis running locally (for WebSocket chat)

### 2. Clone and set up environment

```bash
git clone <repo-url>
cd StallManagement

# Create and activate a virtual environment
python -m venv venv
source venv/bin/activate          # Linux/Mac
venv\Scripts\activate             # Windows

# Install dependencies
pip install -r requirements.txt
pip install -r requirements-dev.txt   # for tests
```

### 3. Configure environment variables

```bash
cp .env.example .env
# Edit .env and fill in your MySQL password and a new SECRET_KEY
```

Generate a secret key:
```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

### 4. Set up the database

```bash
# Create the database in MySQL
mysql -u root -p -e "CREATE DATABASE db_market CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"

# Import the schema and seed data
mysql -u root -p db_market < db_market.sql

# Run Django migrations
python manage.py migrate
```

### 5. Start the development server

**With WebSocket support (recommended):**
```bash
daphne StallManagement.asgi:application --port 8000 --bind 127.0.0.1
```

**HTTP only (no chat):**
```bash
python manage.py runserver
```

Open **http://127.0.0.1:8000** in your browser.

### 6. Seed user accounts

The `db_market.sql` file creates three sample users (all with password `123456`):

| Username | Password | Role |
|---|---|---|
| `admin` | `123456` | Admin |
| `owner1` | `123456` | Stall Owner |
| `customer1` | `123456` | Customer |

## API Overview

All endpoints return a consistent JSON envelope:

```json
{
    "success": true,
    "code":    200,
    "message": "Human-readable description",
    "data":    { }
}
```

### Authentication

```
POST /api/auth/login/     { username, password } → { token, user }
POST /api/auth/logout/
GET  /api/auth/me/
```

### Core endpoints

```
/api/users/         User management (admin only)
/api/customers/     External contacts — suppliers & buyers
/api/categories/    Product categories
/api/products/      Inventory products
/api/stalls/        Stall management
/api/inorders/      Inbound (purchase) orders
/api/outorders/     Outbound (sales) orders
/api/favorites/     Product favourites
/api/chat/          Chat REST endpoints
```

### WebSocket

```
ws://localhost:8000/ws/chat/<other_user_id>/
```

## Running Tests

```bash
# All tests
pytest

# With coverage report
pytest --cov=apps --cov=utils --cov-report=term-missing

# Specific test file
pytest tests/test_outorder.py -v

# Run only tests matching a keyword
pytest -k "stock"
```

## Docker (optional)

```bash
docker-compose up --build
```

Services started: `web` (Daphne on port 8000), `db` (MySQL 8.0), `redis` (Redis 7).

## Stock Safety Model

Stock is **never written directly** through the API. All stock changes go through `utils.helpers.adjust_stock()`:

- **Inbound order completed** → `adjust_stock(+amount)` per line (signal)
- **Outbound order completed** → stock check with `SELECT FOR UPDATE` + `adjust_stock(-amount)` per line (signal)
- **Outbound order cancelled** (from completed) → `adjust_stock(+amount)` per line (signal)

All stock operations are wrapped in `transaction.atomic()`. If any step fails, the entire transaction rolls back — no partial stock mutations are possible.

## License

MIT
