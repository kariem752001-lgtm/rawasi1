"""
aqar_core/admin.py
------------------
FIX #1: حذف process_bulk_notifications — انتقلت لـ services.py
FIX #2: حذف manual send_push_notification — الـ signal بيتولاه
FIX #3: Broadcast يستخدم services.send_bulk_notifications
"""
import logging

from django import forms
from django.contrib import admin
from django.contrib.admin import helpers
from django.contrib.auth.admin import UserAdmin
from django.http import HttpResponseRedirect
from django.shortcuts import render

from .models import Announcement, ContactInfo, Notification, SiteSetting, User
from .services import send_bulk_notifications

logger = logging.getLogger(__name__)


class BroadcastForm(forms.Form):
    _selected_action = forms.CharField(widget=forms.MultipleHiddenInput)
    title = forms.CharField(
        max_length=100,
        label="عنوان الإشعار",
        widget=forms.TextInput(attrs={"placeholder": "مثال: تحديث هام"}),
    )
    message = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 4, "placeholder": "اكتب الرسالة..."}),
        label="نص الرسالة",
    )


class CustomUserAdmin(UserAdmin):
    list_display = ("username", "first_name", "phone_number", "client_type", "is_staff", "date_joined")
    list_filter = ("client_type", "is_staff", "is_active", "date_joined")
    search_fields = ("username", "phone_number", "first_name", "email")

    fieldsets = UserAdmin.fieldsets + (
        ("بيانات إضافية", {"fields": ("phone_number", "client_type", "whatsapp_link", "is_agent", "interests")}),
        ("تفضيلات العميل", {"fields": ("interested_in_rent", "interested_in_buy")}),
        ("بيانات النظام", {"fields": ("fcm_token", "is_owner")}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        (
            "بيانات إضافية",
            {
                "classes": ("wide",),
                "fields": ("phone_number", "client_type", "email", "first_name", "last_name"),
            },
        ),
    )

    actions = ["send_broadcast_notification"]

    def send_broadcast_notification(self, request, queryset):
        if "apply" in request.POST:
            form = BroadcastForm(request.POST)
            if form.is_valid():
                title = form.cleaned_data["title"]
                message = form.cleaned_data["message"]
                users_list = list(queryset)

                # FIX: يستخدم services.py بدلاً من threading مباشرة
                count = send_bulk_notifications(
                    users=users_list,
                    title=title,
                    message=message,
                    notification_type="System",
                )

                self.message_user(request, f"✅ تم إرسال الإشعار لـ {count} مستخدم.")
                return HttpResponseRedirect(request.get_full_path())
        else:
            form = BroadcastForm(
                initial={"_selected_action": request.POST.getlist(helpers.ACTION_CHECKBOX_NAME)}
            )
        return render(
            request,
            "admin/broadcast_message.html",
            {"items": queryset, "form": form, "title": "إرسال إشعار للمحددين"},
        )

    send_broadcast_notification.short_description = "📢 إرسال إشعار للمستخدمين المحددين"


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("title", "user", "notification_type", "is_read", "created_at")
    list_filter = ("notification_type", "is_read", "created_at")
    search_fields = ("title", "user__username", "user__phone_number")
    raw_id_fields = ("user",)


@admin.register(Announcement)
class AnnouncementAdmin(admin.ModelAdmin):
    list_display = ("title", "target_audience", "sent_at", "is_sent")
    readonly_fields = ("is_sent", "sent_at")
    list_filter = ("target_audience", "is_sent")

    def save_model(self, request, obj, form, change):
        if not change and not obj.is_sent:
            users_to_notify = User.objects.filter(is_active=True)
            if obj.target_audience != "ALL":
                users_to_notify = users_to_notify.filter(client_type=obj.target_audience)

            # FIX: يستخدم services.py — بدون threading مباشرة
            count = send_bulk_notifications(
                users=users_to_notify,
                title=obj.title,
                message=obj.message,
                notification_type="System",
            )

            obj.is_sent = True
            super().save_model(request, obj, form, change)
            self.message_user(request, f"✅ تم إرسال الإعلان الجماعي لـ {count} مستخدم.")
        else:
            super().save_model(request, obj, form, change)


@admin.register(ContactInfo)
class ContactInfoAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return not ContactInfo.objects.exists()


@admin.register(SiteSetting)
class SiteSettingAdmin(admin.ModelAdmin):
    list_display = ("key", "value")
    search_fields = ("key", "value")


admin.site.register(User, CustomUserAdmin)
