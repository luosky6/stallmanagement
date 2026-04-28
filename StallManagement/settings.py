"""
Django Settings for StallManagement Project
============================================
Stack : Python 3.7 · Django 3.2 · MySQL 8.0 · Django Channels 3.x
Auth  : Custom User model (apps.user.models.User) with role-based access
API   : Django REST Framework (DRF)
WS    : Django Channels over ASGI (chat module)
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# 0. Load environment variables from .env
# ---------------------------------------------------------------------------
load_dotenv()

# ---------------------------------------------------------------------------
# 1. Base paths
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# 2. Security
# ---------------------------------------------------------------------------
SECRET_KEY = os.getenv('DJANGO_SECRET_KEY', 'password')

DEBUG = os.getenv('DJANGO_DEBUG', 'True') == 'True'

ALLOWED_HOSTS = os.getenv('DJANGO_ALLOWED_HOSTS', '127.0.0.1,localhost').split(',')

# ---------------------------------------------------------------------------
# 3. Custom User Model
#    Must be declared BEFORE any migration is run.
#    Points to apps/user/models.py → class User(AbstractBaseUser)
# ---------------------------------------------------------------------------
AUTH_USER_MODEL = 'user.User'

# ---------------------------------------------------------------------------
# 4. Installed Applications
# ---------------------------------------------------------------------------
INSTALLED_APPS = [
    # Django built-ins
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    # Third-party
    'rest_framework',           # Django REST Framework
    'rest_framework.authtoken', # Token-based authentication
    'channels',                 # Django Channels (WebSocket support)
    'django_filters',           # django-filter integration with DRF

    # Project apps  (order matters: user must come before apps that FK to it)
    'apps.user',
    'apps.common',
    'apps.customer',
    'apps.category',
    'apps.product',
    'apps.stall',
    'apps.inorder',
    'apps.outorder',
    'apps.favorite',
    'apps.chat',
]

# ---------------------------------------------------------------------------
# 5. Middleware
# ---------------------------------------------------------------------------
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',

    # Custom middleware: logs every request and checks role on protected routes
    'apps.common.middleware.RequestLoggingMiddleware',
]

# ---------------------------------------------------------------------------
# 6. URL configuration
# ---------------------------------------------------------------------------
ROOT_URLCONF = 'StallManagement.urls'

# ---------------------------------------------------------------------------
# 7. Templates
#    index.html (Vue 3 SPA) lives in templates/ and is served at GET /
# ---------------------------------------------------------------------------
TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],   # templates/index.html → SPA entry point
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

# ---------------------------------------------------------------------------
# 8. WSGI / ASGI
# ---------------------------------------------------------------------------
WSGI_APPLICATION = 'StallManagement.wsgi.application'
ASGI_APPLICATION  = 'StallManagement.asgi.application'   # Required by Channels

# ---------------------------------------------------------------------------
# 9. Database — MySQL 8.0
#    Credentials come from .env; never hard-code secrets.
# ---------------------------------------------------------------------------
DATABASES = {
    'default': {
        'ENGINE'  : 'django.db.backends.mysql',
        'NAME'    : os.getenv('DB_NAME',     'db_market'),
        'USER'    : os.getenv('DB_USER',     'root'),
        'PASSWORD': os.getenv('DB_PASSWORD', 'password'),
        'HOST'    : os.getenv('DB_HOST',     '127.0.0.1'),
        'PORT'    : os.getenv('DB_PORT',     '3306'),
        'OPTIONS' : {
            'charset'       : 'utf8mb4',
            'init_command'  : "SET sql_mode='STRICT_TRANS_TABLES'",
            # Keep connections alive for better performance
            'connect_timeout': 10,
        },
    }
}

# ---------------------------------------------------------------------------
# 10. Django Channels — Channel Layers
#     Uses Redis as the backing store for WebSocket message passing.
#     Redis URL comes from .env (REDIS_URL).
#     For local development without Redis, InMemoryChannelLayer can be used
#     (not suitable for production / multi-process deployments).
# ---------------------------------------------------------------------------
REDIS_URL = os.getenv('REDIS_URL', 'redis://127.0.0.1:6379')

CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels_redis.core.RedisChannelLayer',
        'CONFIG' : {
            'hosts': [REDIS_URL],
        },
    },
}

# ---------------------------------------------------------------------------
# 11. Password validation
# ---------------------------------------------------------------------------
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# ---------------------------------------------------------------------------
# 12. Internationalisation
# ---------------------------------------------------------------------------
LANGUAGE_CODE = 'en-us'
TIME_ZONE     = 'Asia/Singapore'   # UTC+8, matching the stall's locale
USE_I18N      = True
USE_L10N      = True
USE_TZ        = True               # Store datetimes as UTC in DB, convert on display

# ---------------------------------------------------------------------------
# 13. Static files (CSS, JS — NOT the SPA html)
# ---------------------------------------------------------------------------
STATIC_URL  = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']   # Development source
STATIC_ROOT = BASE_DIR / 'staticfiles'     # collectstatic target (production)

# ---------------------------------------------------------------------------
# 14. Default primary key type
# ---------------------------------------------------------------------------
DEFAULT_AUTO_FIELD = 'django.db.models.AutoField'

# ---------------------------------------------------------------------------
# 15. Django REST Framework
# ---------------------------------------------------------------------------
REST_FRAMEWORK = {
    # Default authentication: session (browser) + token (API clients / Vue)
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.TokenAuthentication',
        'rest_framework.authentication.SessionAuthentication',
    ],

    # All endpoints require login unless explicitly marked AllowAny
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],

    # Pagination: 20 items per page
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 20,

    # Filtering
    'DEFAULT_FILTER_BACKENDS': [
        'django_filters.rest_framework.DjangoFilterBackend',
        'rest_framework.filters.SearchFilter',
        'rest_framework.filters.OrderingFilter',
    ],

    # Consistent error responses
    'EXCEPTION_HANDLER': 'utils.exceptions.custom_exception_handler',
}

# ---------------------------------------------------------------------------
# 16. Session configuration
#     Sessions stored in the database; expire after 8 hours of inactivity.
# ---------------------------------------------------------------------------
SESSION_ENGINE         = 'django.contrib.sessions.backends.db'
SESSION_COOKIE_AGE     = 60 * 60 * 8   # 8 hours in seconds
SESSION_SAVE_EVERY_REQUEST = True       # Slide the expiry window on each request
SESSION_COOKIE_HTTPONLY    = True       # JS cannot read the session cookie
SESSION_COOKIE_SAMESITE    = 'Lax'

# ---------------------------------------------------------------------------
# 17. CSRF
# ---------------------------------------------------------------------------
CSRF_COOKIE_HTTPONLY = False  # Vue needs to read the CSRF token from JS
CSRF_TRUSTED_ORIGINS = os.getenv(
    'CSRF_TRUSTED_ORIGINS', 'http://127.0.0.1:8000,http://localhost:8000'
).split(',')

# ---------------------------------------------------------------------------
# 18. Logging
#     Three handlers: console (dev), django.log, error.log
#     api.log captures every DRF request via the custom middleware
# ---------------------------------------------------------------------------
LOGGING = {
    'version'                 : 1,
    'disable_existing_loggers': False,

    'formatters': {
        'verbose': {
            'format': '[{asctime}] {levelname} {name} {process:d} {thread:d} — {message}',
            'style' : '{',
        },
        'simple': {
            'format': '[{asctime}] {levelname} — {message}',
            'style' : '{',
        },
    },

    'handlers': {
        'console': {
            'class'    : 'logging.StreamHandler',
            'formatter': 'simple',
        },
        'django_file': {
            'class'    : 'logging.handlers.RotatingFileHandler',
            'filename' : BASE_DIR / 'logs' / 'django.log',
            'maxBytes' : 1024 * 1024 * 5,   # 5 MB
            'backupCount': 3,
            'formatter': 'verbose',
        },
        'error_file': {
            'class'    : 'logging.handlers.RotatingFileHandler',
            'filename' : BASE_DIR / 'logs' / 'error.log',
            'maxBytes' : 1024 * 1024 * 5,
            'backupCount': 3,
            'formatter': 'verbose',
            'level'    : 'ERROR',
        },
        'api_file': {
            'class'    : 'logging.handlers.RotatingFileHandler',
            'filename' : BASE_DIR / 'logs' / 'api.log',
            'maxBytes' : 1024 * 1024 * 5,
            'backupCount': 3,
            'formatter': 'verbose',
        },
    },

    'loggers': {
        # Root Django logger → django.log + console
        'django': {
            'handlers' : ['console', 'django_file', 'error_file'],
            'level'    : 'INFO',
            'propagate': True,
        },
        # API request logger (fed by RequestLoggingMiddleware) → api.log
        'api': {
            'handlers' : ['api_file', 'console'],
            'level'    : 'INFO',
            'propagate': False,
        },
        # App-level logger (used inside any apps/* module)
        'apps': {
            'handlers' : ['console', 'django_file', 'error_file'],
            'level'    : 'DEBUG' if DEBUG else 'INFO',
            'propagate': False,
        },
    },
}
