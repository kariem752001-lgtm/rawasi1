import re
import pusher
from django.conf import settings
from rest_framework.exceptions import ValidationError

app_id = getattr(settings, 'PUSHER_APP_ID', None) or '1234567'
key = getattr(settings, 'PUSHER_KEY', None) or 'dummy_key'
secret = getattr(settings, 'PUSHER_SECRET', None) or 'dummy_secret'
cluster = getattr(settings, 'PUSHER_CLUSTER', 'eu')

pusher_client = pusher.Pusher(
    app_id=app_id,
    key=key,
    secret=secret,
    cluster=cluster,
    ssl=True
)

def validate_no_phone_numbers(text):
    """
    دالة ذكية لاكتشاف أي محاولة لإرسال رقم هاتف (عربي/إنجليزي)
    حتى لو بين الأرقام مسافات أو رموز.
    """
    arabic_digits = "٠١٢٣٤٥٦٧٨٩"
    english_digits = "0123456789"
    translation_table = str.maketrans(arabic_digits, english_digits)
    cleaned_text = text.translate(translation_table)

    # مسح المسافات والرموز الشائعة التي تستخدم للتحايل
    normalized_text = re.sub(r'[\s\-\_\.\,\+]', '', cleaned_text)

    # البحث عن أي سلسلة من 8 إلى 15 رقم متصل
    if re.search(r'\d{8,15}', normalized_text):
        raise ValidationError("عفواً، غير مسموح بمشاركة أرقام الهواتف داخل المحادثة لحمايتك.")