"""
aqar_core/signals.py
--------------------
FIX: إزالة الـ double-fire.
الـ signal ده بيشتغل بس لما يتعمل Notification.objects.create() مباشرة.
لما بنستخدم bulk_create (من services.py)، الـ signal ما بيشتغلش — ده مقصود
عشان services.py بتتعامل مع الـ FCM بنفسها.
"""
import logging

from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from .fcm_manager import send_push_notification
from .models import Notification

logger = logging.getLogger(__name__)


@receiver(post_save, sender=Notification)
def on_notification_created(sender, instance, created, **kwargs):
    """
    بيبعت FCM بعد إنشاء الإشعار فقط (مش عند التعديل).
    transaction.on_commit: يضمن إن الـ DB اتحفظ فعلاً قبل الإرسال.
    ملاحظة: bulk_create لا يطلق هذا الـ signal — تصميم مقصود.
    """
    if not created:
        return

    transaction.on_commit(
        lambda: send_push_notification(
            user=instance.user,
            title=instance.title,
            body=instance.message,
            link="/",
        )
    )
