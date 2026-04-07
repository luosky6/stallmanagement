# Setup Guide

This guide walks you through setting up the StallManagement project from scratch on your local machine, and preparing it for production deployment.

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Local Development Setup](#2-local-development-setup)
3. [Database Setup](#3-database-setup)
4. [Environment Configuration](#4-environment-configuration)
5. [Running the Server](#5-running-the-server)
6. [Running Tests](#6-running-tests)
7. [Docker Setup](#7-docker-setup)
8. [Project File Structure](#8-project-file-structure)
9. [Troubleshooting](#9-troubleshooting)

---

## 1. Prerequisites

Before starting, make sure the following are installed on your machine.

### Required

| Software | Version | Download |
|---|---|---|
| Python | 3.7 or higher | https://www.python.org/downloads/ |
| MySQL | 8.0 | https://dev.mysql.com/downloads/mysql/ |
| Redis | 6.0 or higher | https://redis.io/download |
| Git | any | https://git-scm.com/ |

### Optional (for Docker setup)

| Software | Version | Download |
|---|---|---|
| Docker Desktop | latest | https://www.docker.com/products/docker-desktop/ |
| Docker Compose | included with Docker Desktop | — |

### Verify your installations

```bash
python --version        # Python 3.7.x or higher
mysql --version         # mysql  Ver 8.0.x
redis-cli --version     # Redis cli 6.x.x or higher
git --version           # git version 2.x.x
```

---

## 2. Local Development Setup

### Step 1 — Clone the repository

```bash
git clone <your-repo-url>
cd StallManagement
```

### Step 2 — Create a virtual environment

```bash
# Create the virtual environment
python -m venv venv

# Activate it
# On macOS / Linux:
source venv/bin/activate

# On Windows (Command Prompt):
venv\Scripts\activate.bat

# On Windows (PowerShell):
venv\Scripts\Activate.ps1
```

You should see `(venv)` appear at the start of your terminal prompt.

### Step 3 — Install Python dependencies

```bash
# Core dependencies
pip install -r requirements.txt

# Development and testing tools (optional but recommended)
pip install -r requirements-dev.txt
```

> **Note for Windows users:** `mysqlclient` requires the MySQL C connector. If the install fails, download the MySQL Connector/C from https://dev.mysql.com/downloads/connector/c/ and try again.

> **Note for Linux users:** Install the system package first:
> ```bash
> sudo apt-get install default-libmysqlclient-dev gcc pkg-config
> ```

### Step 4 — Create the logs directory

The logging configuration writes to files in `logs/`. Create the directory if it does not exist:

```bash
mkdir -p logs
```

---

## 3. Database Setup

### Step 1 — Start MySQL

Make sure your MySQL 8.0 server is running.

```bash
# macOS (Homebrew)
brew services start mysql

# Linux (systemd)
sudo systemctl start mysql

# Windows — start from the MySQL Notifier in the system tray,
# or from Services in Task Manager
```

### Step 2 — Create the database

Log in to MySQL and create the database:

```bash
mysql -u root -p
```

Inside the MySQL prompt:

```sql
CREATE DATABASE db_market
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

EXIT;
```

### Step 3 — Import the schema and seed data

```bash
mysql -u root -p db_market < db_market.sql
```

This imports all tables and the sample data including three user accounts.

### Step 4 — Run Django migrations

```bash
python manage.py migrate
```

This applies Django's internal tables (sessions, auth tokens, content types) on top of the schema you just imported.

---

## 4. Environment Configuration

### Step 1 — Copy the template

```bash
cp .env.example .env
```

### Step 2 — Fill in your values

Open `.env` in a text editor and update the following:

**`DJANGO_SECRET_KEY`** — generate a new key:
```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```
Paste the output as the value.

**`DB_PASSWORD`** — your MySQL root (or user) password. Leave blank if your local MySQL has no password:
```
DB_PASSWORD=
```

**Everything else** can stay at the default values for local development.

### Final `.env` for local development

```
DJANGO_SECRET_KEY=<your-generated-key>
DJANGO_DEBUG=True
DJANGO_ALLOWED_HOSTS=127.0.0.1,localhost

DB_NAME=db_market
DB_USER=root
DB_PASSWORD=<your-mysql-password>
DB_HOST=127.0.0.1
DB_PORT=3306

REDIS_URL=redis://127.0.0.1:6379
CSRF_TRUSTED_ORIGINS=http://127.0.0.1:8000,http://localhost:8000
```

---

## 5. Running the Server

### Option A — With WebSocket support (recommended)

Use Daphne (the ASGI server) so that the real-time chat WebSocket works:

```bash
daphne StallManagement.asgi:application --port 8000 --bind 127.0.0.1
```

### Option B — Standard Django dev server (no WebSocket)

```bash
python manage.py runserver
```

> The chat tab will not work in real time with this option because Django's built-in server does not support WebSocket connections.

### Open the application

Visit **http://127.0.0.1:8000** in your browser.

### Sample login accounts

All seed accounts use the password `123456`.

| Username | Role | Access |
|---|---|---|
| `admin` | Admin | Full system access |
| `owner1` | Stall Owner | Products, orders, inventory |
| `customer1` | Customer | Browse products, favourites, chat |

---

## 6. Running Tests

Make sure you have installed `requirements-dev.txt` and that your `.env` is configured.

```bash
# Run all tests
pytest

# Run with verbose output
pytest -v

# Run a specific test file
pytest tests/test_product.py -v
pytest tests/test_outorder.py -v

# Run tests matching a keyword
pytest -k "stock"
pytest -k "complete"

# Run with coverage report
pytest --cov=apps --cov=utils --cov-report=term-missing

# Stop on the first failure
pytest -x
```

### What each test file covers

| File | What it tests |
|---|---|
| `test_user.py` | User model, login/logout, CRUD, role checks, soft-delete |
| `test_product.py` | Product CRUD, search, filter, stock protection, permissions |
| `test_inorder.py` | Inbound orders, stock increase signal, idempotency |
| `test_outorder.py` | Outbound orders, stock check, atomic rollback, cancellation |
| `test_chat.py` | REST chat endpoints + WebSocket consumer (async) |

---

## 7. Docker Setup

Use Docker if you want to run the entire stack (Django + MySQL + Redis) without installing MySQL or Redis locally.

### Step 1 — Make sure Docker Desktop is running

### Step 2 — Build and start all services

```bash
docker-compose up --build
```

On the first run this will:
- Build the Django image from the `Dockerfile`
- Pull the MySQL 8.0 and Redis 7 images
- Start all three services
- Auto-import `db_market.sql` into MySQL
- Run Django migrations
- Start the Daphne server

### Step 3 — Open the application

Visit **http://localhost:8000**.

### Useful Docker commands

```bash
# Start in the background
docker-compose up -d

# View running containers
docker-compose ps

# View application logs
docker-compose logs web

# Follow logs in real time
docker-compose logs -f web

# Stop all services
docker-compose down

# Stop and delete all data (volumes)
docker-compose down -v

# Rebuild after code changes
docker-compose up --build
```

### Connecting to MySQL inside Docker

```bash
docker-compose exec db mysql -u stalluser -pstallpass db_market
```

---

## 8. Project File Structure

```
StallManagement/
│
├── StallManagement/          Django configuration
│   ├── settings.py           Global settings, database, logging
│   ├── urls.py               Global URL routing
│   ├── asgi.py               ASGI entry point (HTTP + WebSocket)
│   └── wsgi.py               WSGI entry point (HTTP only)
│
├── apps/                     All application modules
│   ├── common/               Login, logout, SPA entry point, middleware
│   ├── user/                 Custom user model (role-based auth)
│   ├── customer/             External contacts (suppliers & buyers)
│   ├── category/             Product categories
│   ├── product/              Inventory products and stock levels
│   ├── stall/                Stall management (activate/suspend)
│   ├── inorder/              Inbound purchase orders + stock increase
│   ├── outorder/             Outbound sales orders + stock deduction
│   ├── favorite/             Product favourites per user
│   └── chat/                 Real-time chat (WebSocket + REST)
│
├── api/                      URL routing layer (thin pass-through)
│   ├── urls.py               Master API router
│   ├── permissions.py        DRF permission classes
│   ├── authentication.py     Custom auth (soft-delete aware)
│   ├── filters.py            django-filter FilterSets
│   └── user|product|...      Per-domain sub-packages
│
├── utils/                    Shared utilities
│   ├── helpers.py            adjust_stock() — the only stock mutation path
│   ├── constants.py          Role names, status values, thresholds
│   ├── exceptions.py         InsufficientStockError, custom DRF handler
│   ├── decorators.py         @admin_required, @stall_owner_required
│   └── validators.py         Input validation functions
│
├── templates/
│   └── index.html            Vue 3 SPA — served at GET /
│
├── static/                   CSS/JS assets (future use)
├── logs/                     Rotating log files
├── tests/                    pytest test suite
└── docs/                     This documentation
```

---

## 9. Troubleshooting

### `mysqlclient` fails to install

**Linux:**
```bash
sudo apt-get install python3-dev default-libmysqlclient-dev build-essential pkg-config
pip install mysqlclient
```

**macOS:**
```bash
brew install mysql-client
export PKG_CONFIG_PATH="/usr/local/opt/mysql-client/lib/pkgconfig"
pip install mysqlclient
```

**Windows:** Download and install MySQL Connector/C from https://dev.mysql.com/downloads/connector/c/, then retry `pip install mysqlclient`.

---

### `django.db.utils.OperationalError: (2002, "Can't connect to MySQL server")`

MySQL is not running. Start it:
```bash
# macOS
brew services start mysql

# Linux
sudo systemctl start mysql
```

---

### `redis.exceptions.ConnectionError: Error connecting to Redis`

Redis is not running. Start it:
```bash
# macOS
brew services start redis

# Linux
sudo systemctl start redis

# Any platform (foreground)
redis-server
```

---

### `django.db.utils.OperationalError: (1049, "Unknown database 'db_market'")`

The database does not exist yet. Create it:
```bash
mysql -u root -p -e "CREATE DATABASE db_market CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
```

---

### Port 8000 is already in use

```bash
# Find the process using port 8000
# macOS / Linux
lsof -i :8000

# Windows
netstat -ano | findstr :8000

# Then kill it, or run Django on a different port
python manage.py runserver 8001
daphne StallManagement.asgi:application --port 8001
```

---

### WebSocket chat is not connecting

1. Make sure you are using **Daphne**, not `runserver`.
2. Make sure **Redis is running** — Channels requires it for the channel layer.
3. Check that `REDIS_URL` in your `.env` is correct (`redis://127.0.0.1:6379`).
4. Check the browser console for WebSocket connection errors.

---

### Tests fail with `django.db.utils.OperationalError`

Make sure your `.env` database credentials are correct and MySQL is running. Pytest-django creates a separate test database automatically, but it still needs to connect to MySQL to do so.
