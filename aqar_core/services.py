"""
aqar_core/services.py
---------------------
طبقة الـ Business Logic المركزية.
كل الدوال المشتركة بين admin.py وviews.py تعيش هنا.
"""
import logging
from .models import Notification
from .fcm_manager import send_push_notification_bulk

logger = logging.getLogger(__name__)


def send_bulk_notifications(users, title, message, notification_type="System", link="/"):
    """
    إرسال إشعار جماعي: يحفظ في DB ويرسل FCM في خطوة واحدة.

    الميزات:
    - bulk_create لحفظ كل الإشعارات في query واحدة
    - FCM batch لإرسال الكل في request واحدة
    - Logging في حالة الخطأ

    Args:
        users: list أو queryset من User objects
        title: عنوان الإشعار
        message: نص الرسالة
        notification_type: 'System' | 'Listing' | 'Offer'
        link: الرابط عند الضغط على الإشعار
    """
    if not users:
        logger.warning("send_bulk_notifications called with empty users list")
        return 0

    users_list = list(users)  # تحويل queryset لـ list مرة واحدة

    # 1. حفظ الإشعارات في الـ DB بـ bulk_create (query واحدة)
    notifications = [
        Notification(
            user=user,
            title=title,
            message=message,
            notification_type=notification_type,
        )
        for user in users_list
    ]

    try:
        Notification.objects.bulk_create(notifications, ignore_conflicts=True)
        logger.info(f"Bulk created {len(notifications)} notifications: '{title}'")
    except Exception as e:
        logger.error(f"Failed to bulk create notifications: {e}")
        raise

    # 2. إرسال FCM (الـ signal لن يشتغل مع bulk_create عمداً)
    # نستدعي الإرسال هنا بشكل صريح
    tokens = [u.fcm_token for u in users_list if u.fcm_token]
    if tokens:
        send_push_notification_bulk(tokens=tokens, title=title, body=message, link=link)

    return len(users_list)
