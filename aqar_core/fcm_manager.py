"""
aqar_core/fcm_manager.py
------------------------
FIX #1: serviceAccountKey.json مش في الكود — بييجي من ENV variable
FIX #2: إضافة send_push_notification_bulk لإرسال جماعي بـ Firebase batch API
"""
import json
import logging
import os
import threading

import firebase_admin
from django.conf import settings
from firebase_admin import credentials, messaging

logger = logging.getLogger(__name__)

_firebase_lock = threading.Lock()


def ensure_firebase_initialized() -> bool:
    """
    Lazy initialization لـ Firebase مع thread safety.
    FIX: يقرأ الـ credentials من ENV variable بدلاً من ملف على الديسك.
    """
    if firebase_admin._apps:
        return True

    with _firebase_lock:
        # Double-check بعد الـ lock
        if firebase_admin._apps:
            return True

        try:
            # الطريقة الأولى (الأفضل): JSON كامل في ENV variable
            sa_json = os.environ.get("FIREBASE_SA_JSON")
            if sa_json:
                cred_dict = json.loads(sa_json)
                cred = credentials.Certificate(cred_dict)
                firebase_admin.initialize_app(cred)
                logger.info("Firebase initialized from ENV variable (FIREBASE_SA_JSON)")
                return True

            # الطريقة الثانية: مسار الملف من ENV (للـ Development فقط)
            cred_path = os.environ.get(
                "FIREBASE_CREDENTIALS_PATH",
                # fallback للـ local dev فقط، مش الـ production
                os.path.join(settings.BASE_DIR, "serviceAccountKey.json") if settings.DEBUG else None,
            )

            if cred_path and os.path.exists(cred_path):
                cred = credentials.Certificate(cred_path)
                firebase_admin.initialize_app(cred)
                logger.info(f"Firebase initialized from file: {cred_path}")
                return True

            logger.warning("Firebase credentials not found. Push notifications disabled.")
            return False

        except json.JSONDecodeError as e:
            logger.error(f"Invalid FIREBASE_SA_JSON format: {e}")
            return False
        except Exception as e:
            logger.error(f"Firebase initialization failed: {e}")
            return False


def _send_single(user, title: str, body: str, link: str, icon_url: str | None):
    """إرسال إشعار لمستخدم واحد (يستخدم داخلياً)."""
    if not ensure_firebase_initialized():
        return None

    if not user.fcm_token:
        return None

    try:
        fcm_options = None
        if link and link.startswith("https"):
            fcm_options = messaging.WebpushFCMOptions(link=link)

        message = messaging.Message(
            notification=messaging.Notification(
                title=title,
                body=body,
                image=icon_url,
            ),
            data={
                "url": link or "/",
                "click_action": "FLUTTER_NOTIFICATION_CLICK",
            },
            android=messaging.AndroidConfig(
                priority="high",
                notification=messaging.AndroidNotification(
                    icon="ic_stat_r",
                    color="#0f172a",
                    click_action="FLUTTER_NOTIFICATION_CLICK",
                ),
            ),
            webpush=messaging.WebpushConfig(
                headers={"Urgency": "high"},
                notification=messaging.WebpushNotification(
                    icon="/icons/icon-192x192.png",
                    badge="/icons/badge-72x72.png",
                ),
                fcm_options=fcm_options,
            ),
            token=user.fcm_token,
        )

        return messaging.send(message)

    except messaging.UnregisteredError:
        # التوكن منتهي — نمسحه عشان ما نبعتلوش تاني
        logger.info(f"Removing expired FCM token for user {user.pk}")
        user.fcm_token = None
        user.save(update_fields=["fcm_token"])
        return None
    except Exception as e:
        logger.error(f"FCM send failed for user {user.pk}: {e}")
        return None


def send_push_notification(user, title: str, body: str, link: str = "/", icon_url=None):
    """
    إرسال إشعار لمستخدم واحد في الخلفية (Background Thread).
    تُستخدم للإشعارات الفردية من الـ signal.
    """
    thread = threading.Thread(
        target=_send_single,
        args=(user, title, body, link, icon_url),
        daemon=True,  # يموت لو السيرفر وقف — أفضل من thread ضايع
    )
    thread.start()


def send_push_notification_bulk(tokens: list[str], title: str, body: str, link: str = "/"):
    """
    FIX #2: إرسال جماعي بـ Firebase Batch API (طلب واحد لـ 500 token).
    أسرع بكثير من threading لكل مستخدم.
    يُستخدم للإعلانات الجماعية من services.py.
    """
    if not ensure_firebase_initialized() or not tokens:
        return

    def _bulk_task(token_list):
        # Firebase batch: max 500 per request
        chunk_size = 500
        for i in range(0, len(token_list), chunk_size):
            chunk = token_list[i : i + chunk_size]
            messages = [
                messaging.Message(
                    notification=messaging.Notification(title=title, body=body),
                    data={"url": link or "/"},
                    token=token,
                )
                for token in chunk
            ]
            try:
                response = messaging.send_all(messages)
                logger.info(
                    f"FCM Batch: {response.success_count} sent, "
                    f"{response.failure_count} failed (chunk {i // chunk_size + 1})"
                )
            except Exception as e:
                logger.error(f"FCM Batch failed for chunk {i}: {e}")

    thread = threading.Thread(target=_bulk_task, args=(tokens,), daemon=True)
    thread.start()
