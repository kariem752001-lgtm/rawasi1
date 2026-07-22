"""
aqar_core/serializers.py
-------------------------
FIX: NotificationSerializer يحدد الحقول صراحةً بدل __all__
"""
from django.contrib.auth import get_user_model
from djoser.serializers import UserCreateSerializer as BaseUserCreateSerializer
from djoser.serializers import UserSerializer as BaseUserSerializer
from rest_framework import serializers

from .models import Notification, SiteSetting

User = get_user_model()


# ==========================================
# 1. خاص بـ Djoser (التسجيل والبروفايل)
# ==========================================
class CustomUserCreateSerializer(BaseUserCreateSerializer):
    """للتسجيل — يضع رقم الهاتف كـ username تلقائياً."""

    class Meta(BaseUserCreateSerializer.Meta):
        model = User
        fields = ("id", "phone_number", "password", "first_name", "last_name", "client_type")
        extra_kwargs = {
            "phone_number": {"required": True},
            "email": {"required": False},
        }

    def validate(self, attrs):
        if "phone_number" in attrs:
            attrs["username"] = attrs["phone_number"]
        return super().validate(attrs)


class CustomUserSerializer(BaseUserSerializer):
    """لعرض البيانات الشخصية — يتضمن is_staff لزرار الأدمن."""

    class Meta(BaseUserSerializer.Meta):
        model = User
        fields = (
            "id", "username", "first_name", "last_name",
            "phone_number", "is_staff", "is_superuser",
            "client_type", "whatsapp_link", "interests",
        )


# ==========================================
# 2. عام للمشروع
# ==========================================
class UserSerializer(serializers.ModelSerializer):
    """Serializer عام خفيف للعرض فقط — لا يكشف بيانات حساسة."""

    class Meta:
        model = User
        fields = ["id", "first_name", "last_name", "phone_number", "whatsapp_link", "client_type"]


class UserProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = [
            "id", "username", "first_name", "last_name",
            "email", "phone_number", "whatsapp_link",
            "interests", "client_type",
        ]
        read_only_fields = ["username", "id"]


class SiteSettingSerializer(serializers.ModelSerializer):
    class Meta:
        model = SiteSetting
        fields = ["key", "value"]


# FIX: تحديد الحقول صراحةً — لا نكشف created_by أو بيانات غير ضرورية
class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = [
            "id",
            "title",
            "message",
            "is_read",
            "notification_type",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]
