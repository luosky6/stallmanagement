"""
WSGI Configuration for StallManagement
=======================================
This module exposes the WSGI callable as a module-level variable named
``application``.

Use this file with production WSGI servers such as Gunicorn:

    gunicorn StallManagement.wsgi:application --bind 0.0.0.0:8000 --workers 4

Notes
-----
- WSGI handles standard synchronous HTTP requests only.
- WebSocket connections are handled by ASGI (see asgi.py).
- In a deployment that uses both HTTP and WebSocket, point the reverse
  proxy (e.g. Nginx) at the ASGI server (Daphne / Uvicorn) so that both
  protocols go through a single process. The WSGI file is kept for
  environments that do not need WebSocket support.
"""

import os
from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'StallManagement.settings')

application = get_wsgi_application()
