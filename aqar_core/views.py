"""
aqar_core/views.py
------------------
FIX #1: RegisterView تستخدم CustomUserCreateSerializer (passwords محشوشة)
FIX #2: AdminUsersListView تستخدم annotate بدلاً من N+1 loop
FIX #3: AdminUserDetailView.delete — Soft Delete واضح (مش toggle)
FIX #4: AdminBroadcastNotificationView تستخدم services.py
FIX #5: لا import من admin.py
"""
import logging

from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.models import Group
from django.db.models import Count
from django.shortcuts import get_object_or_404
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page
from rest_framework import filters, generics, permissions, status, viewsets
from rest_framework.authtoken.models import Token
from rest_framework.authtoken.views import ObtainAuthToken
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import ContactInfo, Notification
from .serializers import (
    CustomUserCreateSerializer,
    NotificationSerializer,
    UserProfileSerializer,
    UserSerializer,
)
from .services import send_bulk_notifications

logger = logging.getLogger(__name__)
User = get_user_model()


# ==========================================
# Public endpoints
# ==========================================

@api_view(["GET"])
@permission_classes([AllowAny])

def contact_info(request):
    info = ContactInfo.objects.first()
    if info:
        return Response({"support_phone": info.support_phone, "whatsapp_number": info.whatsapp_number})
    return Response({"support_phone": "", "whatsapp_number": ""})


# FIX #1: RegisterView تستخدم CustomUserCreateSerializer
class RegisterView(generics.CreateAPIView):
    queryset = User.objects.all()
    serializer_class = CustomUserCreateSerializer   # ← الإصلاح الجوهري
    permission_classes = [AllowAny]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            user = serializer.save()
            token, _ = Token.objects.get_or_create(user=user)
            return Response(
                {
                    "token": token.key,
                    "user_id": user.pk,
                    "name": user.first_name,
                    "client_type": user.client_type,
                },
                status=status.HTTP_201_CREATED,
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class CustomAuthToken(ObtainAuthToken):
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        phone = request.data.get("phone_number") or request.data.get("username")
        password = request.data.get("password")

        if not phone or not password:
            return Response({"non_field_errors": ["البيانات ناقصة"]}, status=400)

        user_obj = User.objects.filter(phone_number=phone).first()

        if not user_obj:
            # FIX: وقت ثابت حتى لا يكشف الأرقام المسجلة (Timing Attack)
            from django.contrib.auth.hashers import check_password
            check_password("dummy", "pbkdf2_sha256$100000$dummy$dummy")
            return Response({"non_field_errors": ["بيانات الدخول غير صحيحة"]}, status=400)

        if not user_obj.is_active:
            return Response({"non_field_errors": ["هذا الحساب تم إيقافه."]}, status=403)

        user = authenticate(username=user_obj.username, password=password)
        if user:
            token, _ = Token.objects.get_or_create(user=user)
            return Response(
                {
                    "token": token.key,
                    "user_id": user.pk,
                    "name": user.first_name,
                    "client_type": user.client_type,
                    "is_staff": user.is_staff,
                }
            )

        return Response({"non_field_errors": ["بيانات الدخول غير صحيحة"]}, status=400)


class UserProfileView(generics.RetrieveUpdateAPIView):
    serializer_class = UserProfileSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        return self.request.user


class NotificationViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = NotificationSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return (
            Notification.objects
            .filter(user=self.request.user)
            .only("id", "title", "message", "is_read", "notification_type", "created_at")
            .order_by("-created_at")
        )

    @action(detail=False, methods=["post"])
    def mark_all_read(self, request):
        request.user.notifications.filter(is_read=False).update(is_read=True)
        return Response({"status": "success"})


class UpdateFCMTokenView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        fcm_token = request.data.get("fcm_token")
        if fcm_token:
            request.user.fcm_token = fcm_token
            request.user.save(update_fields=["fcm_token"])
            return Response({"status": "updated"})
        return Response({"error": "No token"}, status=400)


class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.filter(is_active=True)
    serializer_class = UserProfileSerializer
    permission_classes = [IsAdminUser]
    filter_backends = [filters.SearchFilter]
    search_fields = ["phone_number", "username", "first_name"]

    def create(self, request, *args, **kwargs):
        serializer = UserSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.save()
            if "password" in request.data:
                user.set_password(request.data["password"])
            if request.data.get("is_staff"):
                user.is_staff = True
            user.save(update_fields=['password', 'is_staff'])

            role_name = request.data.get("role")
            if role_name:
                try:
                    group = Group.objects.get(name=role_name)
                    user.groups.add(group)
                except Group.DoesNotExist:
                    return Response(
                        {"warning": "المستخدم تم إنشاؤه لكن الدور غير موجود"},
                        status=status.HTTP_201_CREATED,
                    )
            return Response(UserSerializer(user).data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def destroy(self, request, *args, **kwargs):
        user = self.get_object()
        if user.is_owner:
            return Response({"detail": "⛔ لا يمكن حذف مالك الموقع."}, status=status.HTTP_403_FORBIDDEN)
        if user == request.user:
            return Response({"detail": "لا يمكن حذف حسابك الحالي."}, status=status.HTTP_400_BAD_REQUEST)

        user.is_active = False
        user.save(update_fields=["is_active"])
        return Response({"detail": "تم إيقاف حساب المستخدم."}, status=status.HTTP_204_NO_CONTENT)

    @action(detail=False, methods=["get"])
    def roles(self, request):
        groups = Group.objects.values("id", "name")
        return Response(groups)


# ==========================================
# Admin Dashboard APIs
# ==========================================

class AdminUsersListView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        # FIX #2: annotate بدلاً من N+1 — query واحدة بدلاً من query لكل مستخدم
        users = (
            User.objects.all()
            .annotate(listings_count=Count("assigned_listings"))
            .order_by("-date_joined")
        )

        client_type_map = dict(User.CLIENT_TYPES)
        data = [
            {
                "id": u.id,
                "name": f"{u.first_name} {u.last_name}".strip() or u.username,
                "first_name": u.first_name,
                "last_name": u.last_name,
                "phone": u.phone_number or "",
                "user_type": client_type_map.get(u.client_type, "مستخدم"),
                "raw_client_type": u.client_type,
                "is_staff": u.is_staff,
                "is_active": u.is_active,
                "date_joined": u.date_joined.strftime("%Y-%m-%d") if u.date_joined else "",
                "listings_count": u.listings_count,
            }
            for u in users
        ]
        return Response(data)


class AdminBroadcastNotificationView(APIView):
    permission_classes = [IsAdminUser]

    def post(self, request):
        title = request.data.get("title")
        message = request.data.get("message")
        target = request.data.get("target", "all")

        if not title or not message:
            return Response({"error": "العنوان والرسالة مطلوبان"}, status=400)

        users = User.objects.filter(is_active=True)

        if target == "Broker":
            users = users.filter(client_type__in=["Marketer", "Seller"])
        elif target == "Client":
            users = users.filter(client_type__in=["Buyer", "Investor"])

        # FIX #4: يستخدم services.py — لا import من admin.py
        count = send_bulk_notifications(users=users, title=title, message=message)
        return Response({"status": "success", "count": count})


class AdminUserDetailView(APIView):
    permission_classes = [IsAdminUser]

    def put(self, request, user_id):
        try:
            user = get_object_or_404(User, id=user_id)

            if getattr(user, "is_owner", False) and request.user.id != user.id:
                return Response({"error": "لا يمكن التعديل على المالك الأساسي"}, status=403)

            user.first_name = request.data.get("first_name", user.first_name)
            user.last_name = request.data.get("last_name", user.last_name)
            user.phone_number = request.data.get("phone", user.phone_number)
            user.client_type = request.data.get("client_type", user.client_type)

            if "is_staff" in request.data:
                user.is_staff = bool(request.data["is_staff"])
            if "is_active" in request.data:
                user.is_active = bool(request.data["is_active"])

            user.save()
            return Response({"status": "success"})
        except Exception as e:
            logger.error(f"AdminUserDetailView PUT error: {e}")
            return Response({"error": str(e)}, status=400)

    def delete(self, request, user_id):
        try:
            user = get_object_or_404(User, id=user_id)

            if getattr(user, "is_owner", False):
                return Response({"error": "لا يمكن إيقاف حساب المالك الأساسي"}, status=403)
            if user.id == request.user.id:
                return Response({"error": "لا يمكنك إيقاف حسابك بنفسك!"}, status=400)

            # FIX #3: Soft Delete واضح — مش toggle
            user.is_active = False
            user.save(update_fields=["is_active"])
            return Response({"status": "success", "is_active": False})
        except Exception as e:
            logger.error(f"AdminUserDetailView DELETE error: {e}")
            return Response({"error": str(e)}, status=400)
