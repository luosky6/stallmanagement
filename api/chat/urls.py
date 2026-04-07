"""
api/chat/urls.py
================
Includes the chat app's URL patterns under /api/chat/.
"""

from django.urls import path, include

urlpatterns = [
    path('chat/', include('apps.chat.urls', namespace='chat')),
]