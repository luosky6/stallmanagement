#!/usr/bin/env python
"""
manage.py
=========
Django's command-line utility for administrative tasks.

Common commands
---------------
    # Start the development server
    python manage.py runserver

    # Start with Channels (ASGI) for WebSocket support
    daphne StallManagement.asgi:application

    # Apply migrations
    python manage.py migrate

    # Create a superuser (admin account)
    python manage.py createsuperuser

    # Generate new migrations after model changes
    python manage.py makemigrations

    # Open the Django shell
    python manage.py shell

    # Collect static files (production)
    python manage.py collectstatic --noinput

    # Run the test suite
    pytest
"""

import os
import sys


def main():
    """Run administrative tasks."""
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'StallManagement.settings')
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == '__main__':
    main()
