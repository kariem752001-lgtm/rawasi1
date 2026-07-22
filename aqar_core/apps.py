from django.apps import AppConfig


class AqarCoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'aqar_core'
    def ready(self):
        # تفعيل الإشارات عند بدء التطبيق
        import aqar_core.signals