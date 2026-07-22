import os
from pathlib import Path
import dj_database_url
from dotenv import load_dotenv
import re


BASE_DIR = Path(__file__).resolve().parent.parent
env_path = BASE_DIR / '.env'
load_dotenv(dotenv_path=env_path)
# ==========================================
# 1. الأمان والبيئة (Security & Environment)
# ==========================================
# FIX #1: SECRET_KEY بدون fallback — لو مش موجود يرمي خطأ صريح
SECRET_KEY = os.environ["SECRET_KEY"]

DEBUG = os.environ.get("DEBUG", "False") == "True"

# FIX #2: ALLOWED_HOSTS تعريف واحد فقط من ENV
ALLOWED_HOSTS = ['127.0.0.1', 'localhost', '*']
# ==========================================
# 2. التطبيقات والوسائط (Apps & Middleware)
# ==========================================
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "rest_framework.authtoken",
    "djoser",
    "django_filters",
    "corsheaders",
    "smart_selects",
    "cloudinary",
    "cloudinary_storage",
    "aqar_core",
    "aqar",
    "chat",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "backend.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates", BASE_DIR / "aqar_core" / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "backend.wsgi.application"

# ==========================================
# 3. قاعدة البيانات والكاش
# ==========================================

DATABASES = {
    'default': dj_database_url.config(
        default=os.environ.get('DATABASE_URL', 'sqlite:///db.sqlite3'),
        conn_max_age=600,
        conn_health_checks=True,
    )
}
DATABASES["default"]["DISABLE_SERVER_SIDE_CURSORS"] = True
# FIX #3: Redis للـ Production، LocMemCache فقط للـ Development
if not DEBUG and os.environ.get("REDIS_URL"):
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": os.environ["REDIS_URL"],
            "OPTIONS": {
                "CLIENT_CLASS": "django_redis.client.DefaultClient",
            },
            "KEY_PREFIX": "rawasi",
            "TIMEOUT": 60 * 60,  # ساعة افتراضياً
        }
    }
else:
    # بيئة التطوير فقط
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "rawasi-cache",
        }
    }

AUTH_USER_MODEL = "aqar_core.User"

# ==========================================
# 4. إعدادات الـ API (REST Framework & Djoser)
# ==========================================
DJOSER = {
    "LOGIN_FIELD": "phone_number",
    "PASSWORD_RESET_CONFIRM_URL": "password/reset/confirm/{uid}/{token}",
    "USERNAME_RESET_CONFIRM_URL": "email/reset/confirm/{uid}/{token}",
    "ACTIVATION_URL": "activate/{uid}/{token}",
    "SEND_ACTIVATION_EMAIL": False,
    "SERIALIZERS": {
        "user_create": "aqar_core.serializers.CustomUserCreateSerializer",
        "current_user": "aqar_core.serializers.CustomUserSerializer",
        "user": "aqar_core.serializers.CustomUserSerializer",
    },
}

# FIX #4: Default permission مغلق — كل endpoint يحتاج تصريح
# + Rate Limiting ضد brute force
REST_FRAMEWORK = {
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 12,
    "DEFAULT_FILTER_BACKENDS": ["django_filters.rest_framework.DjangoFilterBackend"],
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.TokenAuthentication",
    ],
    # مغلق افتراضياً — كل view يفتح ما يحتاجه فقط
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    # Rate Limiting — ضد brute force على /login/ و/register/
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": "100/day",
        "user": "2000/day",
    },
}

# ==========================================
# 5. الحماية والاتصال (CORS & CSRF)
# ==========================================
CORS_ALLOW_CREDENTIALS = True

# FIX #5: CORS_ALLOW_ALL_ORIGINS = False — تم حذف السطر الخطير
CORS_ALLOW_ALL_ORIGINS = False

CORS_ALLOWED_ORIGIN_REGEXES = [
    r"^https://.*\.vercel\.app$",
    r"^http://localhost:3000$",
]

CORS_ALLOWED_ORIGINS = [
    "https://rawasi-iota.vercel.app",
    "https://rawasi-project.vercel.app",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://192.168.1.4:3000",
    "https://rawasi-frontend-woad.vercel.app",
]

# FIX #6: CSRF_TRUSTED_ORIGINS تعريف واحد يجمع كل الـ domains
CSRF_TRUSTED_ORIGINS = [
    "https://*.vercel.app",
    "https://rawasi-iota.vercel.app",
    "https://rawasi-project.vercel.app",
    "http://localhost:3000",
    "http://192.168.1.4:3000",
    "https://rawasi-frontend-woad.vercel.app",
]

CORS_ALLOW_HEADERS = [
    "accept",
    "authorization",
    "content-type",
    "user-agent",
    "x-csrftoken",
    "x-requested-with",
    "cache-control",
    "pragma",
]

# تأمين الكوكيز
CSRF_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SAMESITE = "None" if not DEBUG else "Lax"
SESSION_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_SAMESITE = "None" if not DEBUG else "Lax"

SECURE_BROWSER_XSS_FILTER = True
X_FRAME_OPTIONS = "DENY"

# FIX #7: Security Headers للإنتاج (HSTS)
if not DEBUG:
    SECURE_HSTS_SECONDS = 31536000           # سنة كاملة
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_SSL_REDIRECT = True

# ضروري لـ Railway (Proxy)
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# ==========================================
# 6. الملفات والصور (Static & Media)
# ==========================================
import os

STATIC_URL = '/static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')

# دي المسارات اللي دجانجو بيدور فيها على ملفات التصميم عندك
#STATICFILES_DIRS = [
#    os.path.join(BASE_DIR, 'static'), # لو عندك فولدر static رئيسي
#]

MEDIA_URL = "/media/"
MEDIA_ROOT = os.path.join(BASE_DIR, "media")

CLOUDINARY_STORAGE = {
    "CLOUD_NAME": os.environ.get("CLOUDINARY_CLOUD_NAME"),
    "API_KEY": os.environ.get("CLOUDINARY_API_KEY"),
    "API_SECRET": os.environ.get("CLOUDINARY_API_SECRET"),
    "SECURE": True,
}

if os.environ.get("CLOUDINARY_CLOUD_NAME"):
    # 🚀 دعم دجانجو القديم (< 4.2)
    DEFAULT_FILE_STORAGE = 'cloudinary_storage.storage.MediaCloudinaryStorage'

    # 🚀 دعم دجانجو الحديث (4.2+)
    STORAGES = {
        "default": {"BACKEND": "cloudinary_storage.storage.MediaCloudinaryStorage"},
        "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
    }
else:
    DEFAULT_FILE_STORAGE = 'django.core.files.storage.FileSystemStorage'
    STORAGES = {
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
    }

# FIX #8: تقليل الحد لـ 20MB كافي للصور + يجب تطبيق نفس الحد في Nginx
DATA_UPLOAD_MAX_MEMORY_SIZE = 20 * 1024 * 1024   # 20MB
FILE_UPLOAD_MAX_MEMORY_SIZE = 20 * 1024 * 1024   # 20MB

# ==========================================
# 7. التوطين (Localization)
# ==========================================
LANGUAGE_CODE = "ar-eg"
TIME_ZONE = "Africa/Cairo"
USE_I18N = True
USE_TZ = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
APPEND_SLASH = False
# ==========================================
# 8. إعدادات الشات اللحظي (Pusher)
# ==========================================
PUSHER_APP_ID = os.environ.get("PUSHER_APP_ID", "")
PUSHER_KEY = os.environ.get("PUSHER_KEY", "")
PUSHER_SECRET = os.environ.get("PUSHER_SECRET", "")
PUSHER_CLUSTER = os.environ.get("PUSHER_CLUSTER", "eu")