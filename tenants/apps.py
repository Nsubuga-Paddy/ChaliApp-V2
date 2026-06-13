from django.apps import AppConfig


class TenantsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'tenants'

    def ready(self):
        from django.db.models.signals import post_save

        from .models import Company, CompanyAIConfig

        def create_company_ai_config(sender, instance, created, **kwargs):
            if created:
                CompanyAIConfig.objects.get_or_create(company=instance)

        post_save.connect(create_company_ai_config, sender=Company)
