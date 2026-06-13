from django.apps import AppConfig


class OperationsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'operations'

    def ready(self):
        from django.db.models.signals import post_delete, post_save

        from .models import Message

        def sync_conversation_summary(sender, instance, **kwargs):
            instance.conversation.refresh_message_summary()

        post_save.connect(sync_conversation_summary, sender=Message)
        post_delete.connect(sync_conversation_summary, sender=Message)
