"""
backend/urls.py
---------------
FIX: حذف contact_info المكرر (كان مسجلاً مرتين)
"""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    # المصادقة
    path("api/auth/", include("djoser.urls")),
    path("api/auth/", include("djoser.urls.authtoken")),
    path("api/auth/", include("aqar_core.urls")),

    # لوحة التحكم
    path("admin/", admin.site.urls),

    # Smart Selects (الجغرافيا المترابطة)
    path("chaining/", include("smart_selects.urls")),

    # الـ API الرئيسية
    path("api/", include("aqar.urls")),

    # FIX: contact_info مسجل هنا فقط (مش مرتين)
    # (تأكد إنه محذوف من aqar_core/urls.py لو كان موجود)
]

# الملفات الثابتة والميديا في بيئة التطوير فقط
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)

admin.site.site_header = "لوحة تحكم رواسي"
admin.site.site_title = "بوابة رواسي"
admin.site.index_title = "إدارة النظام"
