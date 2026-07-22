"""
aqar/admin.py
-------------
FIX #1: حذف wildcard import (from .models import *)
FIX #2: approve_listings تستخدم transaction.atomic
FIX #3: Phone sanitization ضد XSS في format_html
FIX #4: reject_listings تستخدم حالة 'Rejected' الصحيحة
"""
import logging
import re

from django.contrib import admin
from django.db import transaction
from django.utils.html import format_html

from aqar_core.models import Notification

try:
    from aqar_core.fcm_manager import send_push_notification
except ImportError:
    def send_push_notification(*args, **kwargs):
        pass

from .models import (
    AnalyticsLog,
    Category,
    Feature,
    Governorate,
    City,
    Listing,
    ListingFeature,
    ListingImage,
    MajorZone,
    Promotion,
    PromotionImage,
    PromotionUnit,
    Subdivision,
    Transformation,
    Waiver,
    WaiverLead,
)
from .utils import trigger_youtube_upload

logger = logging.getLogger(__name__)


def sanitize_phone(phone: str | None) -> str:
    """FIX #3: تنظيف رقم الهاتف قبل استخدامه في format_html (ضد XSS)."""
    if not phone:
        return "غير محدد"
    return re.sub(r"[^0-9+\s\-]", "", phone)


# ==========================================
# Analytics
# ==========================================
@admin.register(AnalyticsLog)
class AnalyticsLogAdmin(admin.ModelAdmin):
    list_display = ("event_type_colored", "get_target_name", "get_visitor_info", "get_total_ad_views", "created_at")
    list_filter = ("event_type", "created_at", ("user", admin.RelatedOnlyFieldListFilter))
    search_fields = ("user__username", "user__first_name", "user__phone_number", "listing__title", "ip_address")
    readonly_fields = ("event_type", "listing", "promotion", "user", "ip_address", "created_at")

    def get_visitor_info(self, obj):
        if obj.user:
            name = f"{obj.user.first_name} {obj.user.last_name}".strip() or obj.user.username
            phone = sanitize_phone(obj.user.phone_number)
            return format_html(
                '<div style="line-height:1.2;">'
                '<span style="font-weight:bold;color:#2c3e50;">👤 {}</span><br>'
                '<span style="font-size:12px;color:#16a085;">📞 {}</span>'
                "</div>",
                name, phone,
            )
        return format_html(
            '<span style="color:#7f8c8d;font-size:12px;">👻 زائر غير مسجل<br>IP: {}</span>',
            obj.ip_address or "",
        )
    get_visitor_info.short_description = "بيانات الزائر"

    def get_total_ad_views(self, obj):
        count = 0
        if obj.listing:
            count = obj.listing.views_count
        elif obj.promotion:
            count = obj.promotion.views_count
        return format_html(
            '<span style="background:#34495e;color:white;padding:3px 8px;border-radius:10px;font-size:12px;">👁️ {} مشاهدة</span>',
            count,
        )
    get_total_ad_views.short_description = "إجمالي المشاهدات"

    def event_type_colored(self, obj):
        colors = {
            "VIEW_LISTING": "gray", "VIEW_PROMO": "gray",
            "CLICK_WHATSAPP": "green", "CLICK_CALL": "blue", "CLICK_PROMO": "orange",
        }
        return format_html(
            '<span style="color:{};font-weight:bold;">{}</span>',
            colors.get(obj.event_type, "black"),
            obj.get_event_type_display(),
        )
    event_type_colored.short_description = "الحدث"

    def get_target_name(self, obj):
        if obj.listing:
            return f"عقار: {obj.listing.title}"
        if obj.promotion:
            return f"إعلان: {obj.promotion.title}"
        return "-"
    get_target_name.short_description = "العنصر المستهدف"


# ==========================================
# Listing Inlines
# ==========================================
class ListingFeatureInline(admin.TabularInline):
    model = ListingFeature
    extra = 1


class ListingImageInline(admin.TabularInline):
    model = ListingImage
    extra = 0
    readonly_fields = ["image_preview"]

    def image_preview(self, obj):
        return format_html('<img src="{}" style="width:100px;height:auto;" />', obj.image.url) if obj.image else ""


# ==========================================
# Listing Admin
# ==========================================
class ListingAdmin(admin.ModelAdmin):
    list_display = ("title", "status_badge", "price", "views_count", "whatsapp_clicks", "get_publisher_summary", "created_at")
    list_filter = ("status", "offer_type", "category", "governorate", "is_finance_eligible")
    search_fields = ("title", "owner_phone", "owner_name", "building_number", "agent__username", "agent__phone_number")
    inlines = [ListingFeatureInline, ListingImageInline]
    actions = ["approve_listings", "reject_listings"]
    readonly_fields = ["get_publisher_details", "get_customer_contact_number", "views_count", "whatsapp_clicks", "call_clicks"]

    fieldsets = (
        ("📊 إحصائيات وحالة الإعلان", {
            "fields": ("status", "is_finance_eligible", "views_count", "whatsapp_clicks", "call_clicks")
        }),
        ("👤 بيانات الناشر والتواصل", {
            "fields": ("get_publisher_details", "get_customer_contact_number"),
        }),
        ("📝 بيانات المالك", {
            "fields": ("agent", "owner_name", "owner_phone")
        }),
        ("🏠 التفاصيل الأساسية", {
            "fields": ("title", "category", "offer_type", "price", "area_sqm", "description")
        }),
        ("تفاصيل الموقع والوحدة", {
            "fields": ("governorate", "city", "major_zone", "subdivision", "project_name",
                       "building_number", "floor_number", "apartment_number", "bedrooms", "bathrooms")
        }),
        ("الموقع على الخريطة", {
            "fields": ("google_maps_url", "latitude", "longitude")
        }),
        ("الوثائق والوسائط", {
            "fields": ("thumbnail", "video", "youtube_url", "custom_map_image", "id_card_image", "contract_image")
        }),
    )

    def save_model(self, request, obj, form, change):
        video_file = request.FILES.get("video")
        if video_file:
            obj.video = None
            trigger_youtube_upload(
                video_file=video_file,
                title=f"عقار رواسي: {obj.title}",
                description=(obj.description or "")[:200],
                instance_model=obj,
            )
        super().save_model(request, obj, form, change)

    def get_publisher_details(self, obj):
        if not obj.agent:
            return "لا يوجد ناشر"
        name = f"{obj.agent.first_name} {obj.agent.last_name}".strip() or obj.agent.username
        phone = sanitize_phone(obj.agent.phone_number)
        return format_html(
            '<div style="background:#e3f2fd;padding:10px;border-radius:5px;border:1px solid #90caf9;">'
            "<strong>الاسم:</strong> {}<br>"
            "<strong>الهاتف:</strong> {}<br>"
            "<strong>النوع:</strong> {}"
            "</div>",
            name, phone, obj.agent.get_client_type_display(),
        )
    get_publisher_details.short_description = "بيانات الناشر"

    def get_customer_contact_number(self, obj):
        # FIX #3: sanitize الرقم قبل استخدامه في HTML
        raw_phone = obj.owner_phone or (obj.agent.phone_number if obj.agent else None)
        contact_phone = sanitize_phone(raw_phone)
        wa_number = re.sub(r"\D", "", contact_phone)
        return format_html(
            '<div style="background:#e8f5e9;padding:10px;border-radius:5px;border:1px solid #a5d6a7;">'
            '<span style="font-size:14px;font-weight:bold;color:green;">📞 {}</span><br>'
            '<a href="https://wa.me/2{}" target="_blank" style="color:#fff;background:#25D366;padding:3px 8px;border-radius:4px;text-decoration:none;">تجربة واتساب</a>'
            "</div>",
            contact_phone, wa_number,
        )
    get_customer_contact_number.short_description = "رقم التواصل للعملاء"

    def get_publisher_summary(self, obj):
        return obj.agent.username if obj.agent else "-"
    get_publisher_summary.short_description = "الناشر"

    @admin.display(description="الحالة")
    def status_badge(self, obj):
        colors = {"Available": "green", "Pending": "orange", "Sold": "red", "Rejected": "#c0392b"}
        return format_html(
            '<span style="color:white;background:{};padding:3px 8px;border-radius:5px;">{}</span>',
            colors.get(obj.status, "gray"),
            obj.get_status_display(),
        )

    # FIX #2: transaction.atomic يضمن الـ rollback لو الإشعارات فشلت
    @transaction.atomic
    def approve_listings(self, request, queryset):
        queryset = queryset.select_related("agent")
        count = 0
        for listing in queryset:
            listing.status = "Available"
            listing.save(update_fields=["status"])
            if listing.agent:
                Notification.objects.create(
                    user=listing.agent,
                    title="مبروك! 🥳",
                    message=f"تم نشر إعلانك '{listing.title}' بنجاح.",
                    notification_type="Listing",
                )
                count += 1
        self.message_user(request, f"تم نشر {count} إعلان.")
    approve_listings.short_description = "✅ قبول ونشر"

    # FIX #4: استخدام 'Rejected' بدل 'Pending' للرفض
    def reject_listings(self, request, queryset):
        queryset.update(status="Rejected")
        self.message_user(request, f"تم رفض {queryset.count()} إعلان.")
    reject_listings.short_description = "⛔ رفض"


admin.site.register(Listing, ListingAdmin)


# ==========================================
# Promotion Inlines & Admin
# ==========================================
class PromotionImageInline(admin.TabularInline):
    model = PromotionImage
    extra = 1
    readonly_fields = ["image_preview"]

    def image_preview(self, obj):
        return format_html('<img src="{}" style="width:100px;height:auto;" />', obj.image.url) if obj.image else ""


class TransformationInline(admin.StackedInline):
    model = Transformation
    extra = 1
    classes = ("collapse",)


class PromotionUnitInline(admin.TabularInline):
    model = PromotionUnit
    extra = 1


@admin.register(Promotion)
class PromotionAdmin(admin.ModelAdmin):
    list_display = ("title", "promo_type", "is_active", "views_count", "clicks_count", "display_order", "created_at")
    list_filter = ("promo_type", "is_active")
    list_editable = ("is_active", "display_order")
    search_fields = ("title", "description", "developer_name")
    readonly_fields = ("views_count", "clicks_count", "whatsapp_clicks", "call_clicks")
    inlines = [PromotionImageInline, TransformationInline, PromotionUnitInline]

    fieldsets = (
        ("الإحصائيات", {"fields": ("views_count", "clicks_count", "whatsapp_clicks", "call_clicks")}),
        ("الإعدادات الأساسية", {"fields": ("title", "subtitle", "promo_type", "cover_image", "developer_logo", "master_plan", "is_active", "display_order")}),
        ("ربط بعقار VIP", {"fields": ("target_listing",)}),
        ("تفاصيل المشروع", {"fields": ("description", "video", "details_video", "youtube_url", "video_url", "developer_name", "payment_system", "delivery_date", "project_features", "price_start_from")}),
        ("الموقع", {"fields": ("latitude", "longitude", "location_url")}),
        ("التواصل", {"fields": ("phone_number", "whatsapp_number")}),
    )

    def save_model(self, request, obj, form, change):
        video_file = request.FILES.get("video")
        if video_file:
            trigger_youtube_upload(
                video_file=video_file,
                title=f"إعلان رواسي: {obj.title}",
                description=(obj.description or "")[:200],
                instance_model=obj,
            )
            obj.video = None
        super().save_model(request, obj, form, change)


# ==========================================
# Other Models
# ==========================================
@admin.register(Feature)
class FeatureAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "input_type", "is_quick_filter", "icon")
    list_filter = ("category", "input_type", "is_quick_filter")
    list_editable = ("is_quick_filter", "input_type", "icon")
    search_fields = ("name",)


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Waiver)
class WaiverAdmin(admin.ModelAdmin):
    list_display = ("plot_number", "neighborhood", "district", "procedure", "committee_number")
    search_fields = ("plot_number", "neighborhood", "district")


@admin.register(WaiverLead)
class WaiverLeadAdmin(admin.ModelAdmin):
    list_display = ("full_name", "phone_number", "plot_number", "neighborhood", "district", "status", "created_at")
    list_filter = ("status", "district")
    search_fields = ("full_name", "phone_number", "plot_number")


admin.site.register(Governorate)
admin.site.register(City)
admin.site.register(MajorZone)
admin.site.register(Subdivision)
