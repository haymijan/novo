# marketing/apps.py

from django.apps import AppConfig

class MarketingConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'marketing'

    def ready(self):
        import marketing.signals # এই লাইনটি যোগ করুন