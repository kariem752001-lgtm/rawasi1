"""
aqar/utils.py
-------------
FIX #1: token.json/credentials.json من ENV variables (مش على الديسك)
FIX #2: sys.getsizeof استبدل بحساب الحجم الصحيح
FIX #3: YouTube credentials من JSON string في ENV
"""
import io
import json
import logging
import os
import sys
import tempfile
import threading

from django.core.files.uploadedfile import InMemoryUploadedFile
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from PIL import Image

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


# ==========================================
# 1. ضغط الصور
# ==========================================
def compress_image(uploaded_image, quality: int = 70):
    """
    ضغط الصورة قبل الرفع إلى Cloudinary.
    FIX: استخدام output.seek(0,2) + output.tell() لحساب الحجم الفعلي.
    """
    if not uploaded_image:
        return None
    try:
        img = Image.open(uploaded_image)
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")

        output = io.BytesIO()
        img.save(output, format="JPEG", quality=quality, optimize=True)

        # FIX: حساب حجم المحتوى الفعلي (مش حجم الـ BytesIO object)
        output.seek(0, 2)          # اذهب لآخر الـ buffer
        file_size = output.tell()  # الحجم الفعلي بالـ bytes
        output.seek(0)             # ارجع للبداية للقراءة

        return InMemoryUploadedFile(
            output,
            "ImageField",
            f"{uploaded_image.name.rsplit('.', 1)[0]}.jpg",
            "image/jpeg",
            file_size,   # ← الحجم الصحيح
            None,
        )
    except Exception as e:
        logger.error(f"Image compression failed for {getattr(uploaded_image, 'name', '?')}: {e}")
        return uploaded_image  # fallback: ارجع الأصل


# ==========================================
# 2. رفع الفيديو لليوتيوب
# ==========================================
def _get_youtube_credentials() -> Credentials | None:
    """
    FIX: يقرأ الـ credentials من ENV variables بدلاً من ملفات على الديسك.
    
    يدعم طريقتين:
    1. YOUTUBE_TOKEN_JSON: JSON string كامل للـ token (الأفضل في الإنتاج)
    2. ملف token.json في بيئة التطوير فقط (لو DEBUG=True)
    """
    from django.conf import settings

    # الطريقة الأولى (الإنتاج): من ENV variable
    token_json_str = os.environ.get("YOUTUBE_TOKEN_JSON")
    if token_json_str:
        try:
            token_data = json.loads(token_json_str)
            return Credentials.from_authorized_user_info(token_data, SCOPES)
        except (json.JSONDecodeError, ValueError) as e:
            logger.error(f"Invalid YOUTUBE_TOKEN_JSON: {e}")
            return None

    # الطريقة الثانية (Development فقط): من ملف محلي
    if settings.DEBUG:
        token_path = os.path.join(settings.BASE_DIR, "token.json")
        if os.path.exists(token_path):
            logger.warning("Using token.json from disk — for development only!")
            return Credentials.from_authorized_user_file(token_path, SCOPES)

    logger.error("YouTube credentials not found. Set YOUTUBE_TOKEN_JSON env variable.")
    return None


def _upload_task(video_file_path: str, title: str, description: str, instance_model):
    """الدالة الفعلية لرفع الفيديو (تشتغل في thread منفصل)."""
    try:
        creds = _get_youtube_credentials()
        if not creds:
            logger.error("YouTube upload aborted: no credentials")
            return

        youtube = build("youtube", "v3", credentials=creds)

        body = {
            "snippet": {
                "title": title[:100],          # YouTube max title length
                "description": description[:5000],
                "categoryId": "22",
            },
            "status": {"privacyStatus": "public"},
        }

        media = MediaFileUpload(video_file_path, chunksize=1024 * 1024 * 5, resumable=True)
        request = youtube.videos().insert(
            part=",".join(body.keys()), body=body, media_body=media
        )
        response = request.execute()

        youtube_id = response.get("id")
        if youtube_id:
            youtube_url = f"https://www.youtube.com/watch?v={youtube_id}"
            instance_model.youtube_url = youtube_url
            instance_model.save(update_fields=["youtube_url"])
            logger.info(f"YouTube upload success: {youtube_url} for {instance_model}")

    except Exception as e:
        logger.error(f"YouTube upload failed for '{title}': {e}")
    finally:
        # تنظيف الملف المؤقت دائماً
        try:
            if os.path.exists(video_file_path):
                os.remove(video_file_path)
                logger.debug(f"Temp file removed: {video_file_path}")
        except Exception as ex:
            logger.warning(f"Failed to remove temp file {video_file_path}: {ex}")


def trigger_youtube_upload(video_file, title: str, description: str, instance_model):
    """
    تستقبل Django UploadedFile، تحفظه مؤقتاً، وتشغل الرفع في thread.
    
    ملاحظة: في الإنتاج يُنصح باستخدام Celery بدلاً من threading.
    """
    try:
        ext = os.path.splitext(video_file.name)[1] or ".mp4"
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=ext)

        for chunk in video_file.chunks():
            temp_file.write(chunk)
        temp_file.close()

        thread = threading.Thread(
            target=_upload_task,
            args=(temp_file.name, title, description, instance_model),
            daemon=True,
        )
        thread.start()
        logger.info(f"YouTube upload thread started for: {title}")

    except Exception as e:
        logger.error(f"Failed to trigger YouTube upload for '{title}': {e}")
