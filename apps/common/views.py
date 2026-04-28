"""
apps/common/views.py
====================
Views handled by the common app:

    IndexView       GET  /              Serves templates/index.html (Vue 3 SPA)
    LoginView       POST /api/auth/login/   Authenticates user, returns DRF token + role
    LogoutView      POST /api/auth/logout/  Invalidates the token, clears the session
    UserProfileView GET  /api/auth/me/      Returns current user's public profile

Response envelope
-----------------
All JSON responses follow a consistent shape so the Vue frontend can handle
them uniformly:

    {
        "success": true | false,
        "code":    200 | 400 | 401 | 403 | ...,
        "message": "Human-readable description",
        "data":    { ... } | null
    }
"""

import logging

from django.shortcuts import render
from django.contrib.auth import authenticate, get_user_model, login, logout
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.views import View
from django.http import HttpResponse
import os
from django.conf import settings
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.authtoken.models import Token

logger = logging.getLogger('apps')
User = get_user_model()


# ---------------------------------------------------------------------------
# Helper: build the standard response envelope
# ---------------------------------------------------------------------------
def ok(data=None, message='Success', code=200):
    """Shortcut for a successful response envelope."""
    return Response(
        {'success': True, 'code': code, 'message': message, 'data': data},
        status=code,
    )


def fail(message='Error', code=400, data=None):
    """Shortcut for a failed response envelope."""
    return Response(
        {'success': False, 'code': code, 'message': message, 'data': data},
        status=code,
    )


def user_payload(user):
    """Public user fields returned to the SPA after auth operations."""
    return {
        'id': user.id,
        'username': user.username,
        'name': user.name,
        'role': user.role,
    }


# ---------------------------------------------------------------------------
# 1. IndexView — serves the Vue 3 SPA entry point
# ---------------------------------------------------------------------------
@method_decorator(ensure_csrf_cookie, name='dispatch')
class IndexView(View):
    """
    GET /

    Renders templates/index.html — the single HTML file for the Vue 3 SPA.

    The ensure_csrf_cookie decorator guarantees that Django sets the
    csrftoken cookie on every page load, even if the Vue app has not yet
    made any POST request.  This lets the Axios/fetch client pick up the
    token from the cookie and attach it as the X-CSRFToken header on
    subsequent API calls (session-auth flow).
    """

    def get(self, request, *args, **kwargs):
        index_path = os.path.join(settings.BASE_DIR, 'templates', 'index.html')
        with open(index_path, 'r', encoding='utf-8') as f:
            content = f.read()
        return HttpResponse(content, content_type='text/html')


# ---------------------------------------------------------------------------
# 2. LoginView — POST /api/auth/login/
# ---------------------------------------------------------------------------
class LoginView(APIView):
    """
    POST /api/auth/login/

    Accepts JSON: { "username": "...", "password": "..." }

    On success:
        - Authenticates the user via Django's auth backend
        - Creates (or retrieves) a DRF auth token
        - Establishes a Django session (for browser clients using the SPA)
        - Returns the token and the user's public profile

    On failure:
        - Returns 401 with a generic message (no hint about which field failed)

    Permission: AllowAny — this endpoint must be reachable before login.
    """

    permission_classes = [AllowAny]

    def post(self, request):
        username = request.data.get('username', '').strip().lower()
        password = request.data.get('password', '').strip()

        # ── Basic input validation ──────────────────────────────────────
        if not username or not password:
            return fail('Username and password are required.', code=400)

        # ── Authenticate ────────────────────────────────────────────────
        user = authenticate(request, username=username, password=password)

        if user is None:
            logger.warning('LoginView: failed login attempt for username="%s"', username)
            return fail('Invalid username or password.', code=401)

        # ── Check account status ────────────────────────────────────────
        if not user.is_active:
            logger.warning('LoginView: disabled account login attempt for username="%s"', username)
            return fail('Your account has been disabled. Please contact the administrator.', code=403)

        # ── Create / retrieve DRF token ─────────────────────────────────
        token, _ = Token.objects.get_or_create(user=user)

        # ── Establish Django session (for SPA browser client) ───────────
        login(request, user)

        logger.info('LoginView: user "%s" (role=%s) logged in successfully.', username, user.role)

        return ok(
            data={
                'token': token.key,
                'user': user_payload(user),
            },
            message='Login successful.',
        )


class RegisterView(APIView):
    """
    POST /api/auth/register/

    Public self-registration endpoint.  New public sign-ups are always created
    as customer users; elevated roles must still be created by an administrator
    through the protected /api/users/ management endpoint.
    """

    permission_classes = [AllowAny]

    def post(self, request):
        username = request.data.get('username', '').strip().lower()
        name = request.data.get('name', '').strip()
        password = request.data.get('password', '')
        password_confirm = request.data.get('password_confirm', '')

        if not username or not name or not password or not password_confirm:
            return fail('Username, display name, password and confirmation are required.', code=400)

        if password != password_confirm:
            return fail('Passwords do not match.', code=400, data={'password_confirm': 'Passwords do not match.'})

        if User.all_objects.filter(username=username).exists():
            return fail('This username is already taken.', code=400, data={'username': 'Already taken.'})

        try:
            validate_password(password)
        except DjangoValidationError as exc:
            return fail('Password does not meet the security requirements.', code=400, data={'password': list(exc.messages)})

        user = User.objects.create_user(
            username=username,
            password=password,
            name=name,
            role=User.Role.CUSTOMER,
        )
        token, _ = Token.objects.get_or_create(user=user)
        login(request, user)

        logger.info('RegisterView: customer "%s" registered and logged in.', username)

        return ok(
            data={'token': token.key, 'user': user_payload(user)},
            message='Registration successful.',
            code=201,
        )


class ForgotPasswordView(APIView):
    """
    POST /api/auth/forgot-password/

    Local recovery flow for the current schema. The users table has no email or
    reset-token fields yet, so this verifies username + display name before
    allowing a password reset. For production, replace this with emailed
    time-limited reset tokens.
    """

    permission_classes = [AllowAny]

    def post(self, request):
        username = request.data.get('username', '').strip().lower()
        name = request.data.get('name', '').strip()
        new_password = request.data.get('new_password', '')
        new_password_confirm = request.data.get('new_password_confirm', '')

        if not username or not name or not new_password or not new_password_confirm:
            return fail('Username, display name, new password and confirmation are required.', code=400)

        if new_password != new_password_confirm:
            return fail('New passwords do not match.', code=400, data={'new_password_confirm': 'New passwords do not match.'})

        user = User.objects.filter(username=username, is_active=True).first()
        if user is None or user.name.strip().lower() != name.lower():
            logger.warning('ForgotPasswordView: failed recovery attempt for username="%s"', username)
            return fail('Account details could not be verified.', code=400)

        try:
            validate_password(new_password, user=user)
        except DjangoValidationError as exc:
            return fail('Password does not meet the security requirements.', code=400, data={'new_password': list(exc.messages)})

        user.set_password(new_password)
        user.save(update_fields=['password'])
        Token.objects.filter(user=user).delete()

        logger.info('ForgotPasswordView: password reset for username="%s".', username)
        return ok(message='Password reset successful. Please sign in with your new password.')


# ---------------------------------------------------------------------------
# 3. LogoutView — POST /api/auth/logout/
# ---------------------------------------------------------------------------
class LogoutView(APIView):
    """
    POST /api/auth/logout/

    Invalidates the user's DRF token and clears the Django session.
    Both mechanisms are cleared so that neither session-auth nor token-auth
    can be reused after logout.

    Permission: IsAuthenticated — only logged-in users can call logout.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        username = user.username

        # ── Delete the DRF token (invalidates API clients) ─────────────
        try:
            request.user.auth_token.delete()
        except Token.DoesNotExist:
            # Token may not exist if the user authenticated via session only
            pass

        # ── Clear the Django session (invalidates SPA browser client) ───
        logout(request)

        logger.info('LogoutView: user "%s" logged out.', username)

        return ok(message='Logged out successfully.')


# ---------------------------------------------------------------------------
# 4. UserProfileView — GET /api/auth/me/
# ---------------------------------------------------------------------------
class UserProfileView(APIView):
    """
    GET /api/auth/me/

    Returns the currently authenticated user's public profile.
    Used by the Vue frontend on page reload to restore the logged-in state
    without re-sending credentials.

    Permission: IsAuthenticated.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        return ok(
            data={
                'id':          user.id,
                'username':    user.username,
                'name':        user.name,
                'role':        user.role,
                'is_active':   user.is_active,
                'create_time': user.create_time.isoformat() if hasattr(user, 'create_time') else None,
            },
            message='Profile retrieved successfully.',
        )
