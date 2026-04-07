from django.apps import AppConfig

class ChatConfig(AppConfig):
    name  = 'apps.chat'
    label = 'chat'
    def ready(self):
        pass