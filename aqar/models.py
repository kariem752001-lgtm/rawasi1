from django.db import models
from django.utils.text import slugify
from django.contrib.auth import get_user_model
from smart_selects.db_fields import ChainedForeignKey
from aqar_core.models import BaseModel
import random, string
from django.db.models.signals import post_save
from django.dispatch import receiver
from cloudinary_storage.storage import VideoMediaCloudinaryStorage
#from .utils import compress_image # ✅ استدعاء دالة الضغط

User = get_user_model()

def generate_ref(): return 'REF-' + ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))

# --- 1. الجغرافيا المرنة ---
class Governorate(models.Model):
    name = models.CharField(max_length=100, unique=True, verbose_name="المحافظة")
    def __str__(self): return self.name

class City(models.Model):
    name = models.CharField(max_length=100, unique=True, verbose_name="المدينة")
    governorate = models.ForeignKey(Governorate, on_delete=models.CASCADE)
    zone_label = models.CharField(max_length=50, default='حي', verbose_name="تسمية المنطقة الكبرى")
    subdivision_label = models.CharField(max_length=50, default='مجاورة', verbose_name="تسمية المنطقة الصغرى")
    def __str__(self): return self.name

class MajorZone(models.Model):
    name = models.CharField(max_length=150)
    city = models.ForeignKey(City, on_delete=models.CASCADE)
    def __str__(self): return f"{self.name}"

class Subdivision(models.Model):
    name = models.CharField(max_length=150)
    major_zone = models.ForeignKey(MajorZone, on_delete=models.CASCADE)
    def __str__(self): return self.name

# --- 2. التصنيف الديناميكي ---
class Category(models.Model):
    name = models.CharField(max_length=50, unique=True, verbose_name="نوع العقار (شقة/أرض)")
    slug = models.SlugField(unique=True, allow_unicode=True)
    def __str__(self): return self.name

class Feature(models.Model):
    category = models.ForeignKey(Category, on_delete=models.CASCADE, related_name='allowed_features')
    name = models.CharField(max_length=100, verbose_name="الخاصية (مثل: رخصة حفر)")
    INPUT_TYPES = [
        ('text', 'نص عادي (Text)'),
        ('bool', 'نعم/لا (Switch)'),
        ('number', 'قيمة رقمية (Buttons + Input)'),
    ]
    input_type = models.CharField(max_length=10, choices=INPUT_TYPES, default='bool', verbose_name="نوع الإدخال")
    is_quick_filter = models.BooleanField(default=False, verbose_name="عرض في الفلتر السريع؟")
    options_list = models.CharField(max_length=200, blank=True, null=True, verbose_name="الأرقام المقترحة")
    ICON_CHOICES = [
        ('CheckCircle2', '✔ علامة صح (افتراضي)'), ('ArrowUpFromLine', '🛗 أسانسير / مصعد'),
        ('Zap', '⚡ كهرباء / عداد'), ('Wind', '💨 غاز طبيعي'), ('Waves', '💧 مياه / سباحة'),
        ('Trees', '🌳 حديقة / لاندسكيب'), ('Car', '🚗 جراج / موقف'), ('Wifi', '📶 واي فاي / إنترنت'),
        ('ShieldCheck', '🛡 أمن وحراسة'), ('Snowflake', '❄ تكييف'), ('Tv', '📺 تلفزيون / دش'),
        ('Paintbucket', '🎨 تشطيب / ديكور'), ('Dumbbell', '💪 جيم / رياضة'),
        ('Utensils', '🍽 مطبخ'), ('BedDouble', '🛏 غرفة نوم'), ('Bath', '🛁 حمام'),
    ]
    icon = models.CharField(max_length=50, choices=ICON_CHOICES, default='CheckCircle2', verbose_name="شكل الأيقونة")
    def __str__(self): return f"{self.name} ({self.category.name})"

# --- 3. العقار ---
class Listing(BaseModel):
    reference_code = models.CharField(max_length=20, default=generate_ref, unique=True)
    title = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255, unique=True, blank=True, allow_unicode=True)
    price = models.DecimalField(max_digits=15, decimal_places=2, db_index=True)
    area_sqm = models.IntegerField(db_index=True)
    description = models.TextField()
    custom_map_image = models.ImageField(upload_to='listings_maps/', null=True, blank=True)
    
    bedrooms = models.IntegerField(null=True, blank=True)
    bathrooms = models.IntegerField(null=True, blank=True)
    floor_number = models.IntegerField(null=True, blank=True)
    building_number = models.CharField(max_length=50, null=True, blank=True)
    apartment_number = models.CharField(max_length=50, null=True, blank=True)
    project_name = models.CharField(max_length=100, null=True, blank=True)

    governorate = models.ForeignKey(Governorate, on_delete=models.CASCADE)
    city = ChainedForeignKey(City, chained_field="governorate", chained_model_field="governorate", show_all=False, auto_choose=True)
    major_zone = ChainedForeignKey(MajorZone, chained_field="city", chained_model_field="city", show_all=False, auto_choose=True)
    subdivision = ChainedForeignKey(Subdivision, chained_field="major_zone", chained_model_field="major_zone", show_all=False, null=True, blank=True)
    
    google_maps_url = models.URLField(null=True, blank=True)
    latitude = models.DecimalField(max_digits=10, decimal_places=8, null=True, blank=True)
    longitude = models.DecimalField(max_digits=10, decimal_places=8, null=True, blank=True)
    
    category = models.ForeignKey(Category, on_delete=models.CASCADE)
    agent = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='assigned_listings')
    
    offer_type = models.CharField(max_length=10, choices=[('Sale', 'بيع'), ('Rent', 'إيجار')], default='Sale', db_index=True)
    STATUS_CHOICES = [('Pending', 'قيد المراجعة'), ('Available', 'متاح'), ('Sold', 'تم البيع'),('Rejected', 'مرفوض')]
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Pending', db_index=True)    
    is_finance_eligible = models.BooleanField(default=False)

    thumbnail = models.ImageField(upload_to='listings_thumbnails/', max_length=500, null=True, blank=True)

    # ✅ تم فصل ملف الفيديو لعدم استهلاك مساحة إذا تم الرفع لليوتيوب
    video = models.FileField(upload_to='listings_videos/', storage=VideoMediaCloudinaryStorage(), null=True, blank=True)   
    youtube_url = models.URLField(null=True, blank=True, verbose_name="رابط فيديو يوتيوب")
    
    id_card_image = models.ImageField(upload_to='secure_docs/', null=True, blank=True)
    contract_image = models.ImageField(upload_to='secure_docs/', null=True, blank=True)
    owner_name = models.CharField(max_length=100, null=True, blank=True)
    owner_phone = models.CharField(max_length=20, null=True, blank=True)

    views_count = models.PositiveIntegerField(default=0, verbose_name="عدد المشاهدات")
    whatsapp_clicks = models.PositiveIntegerField(default=0, verbose_name="نقرات الواتساب")
    call_clicks = models.PositiveIntegerField(default=0, verbose_name="نقرات الاتصال")

    def save(self, *args, **kwargs):
        if not self.slug: 
            self.slug = slugify(self.title, allow_unicode=True) + f"-{self.reference_code}"
        # شلنا كود الضغط من هنا
        if self.youtube_url and self.video:
            self.video = None
        super().save(*args, **kwargs)

    def get_contact_info(self):
        if self.agent and self.agent.phone_number:
            return {'phone': self.agent.phone_number, 'whatsapp': self.agent.whatsapp_link}
        return {'phone': '01000000000', 'whatsapp': 'https://wa.me/201000000000'}

# --- 4. الجداول الفرعية ---
class ListingFeature(models.Model):
    listing = models.ForeignKey(Listing, on_delete=models.CASCADE, related_name='features_values')
    feature = models.ForeignKey(Feature, on_delete=models.CASCADE)
    value = models.CharField(max_length=255)

class ListingImage(models.Model):
    listing = models.ForeignKey(Listing, on_delete=models.CASCADE, related_name='images')
    image = models.ImageField(upload_to='listings_photos/', max_length=500)    
    def save(self, *args, **kwargs):
        # شلنا كود الضغط من هنا
        super().save(*args, **kwargs)
        if not self.listing.thumbnail:
            self.listing.thumbnail = self.image
            self.listing.save(update_fields=['thumbnail'])

class ListingDocument(BaseModel):
    listing = models.ForeignKey(Listing, on_delete=models.CASCADE)
    document_file = models.FileField(upload_to='secure_docs/')
    document_type = models.CharField(max_length=50)

class ZoneMap(models.Model):
    major_zone = models.ForeignKey(MajorZone, on_delete=models.CASCADE, related_name='maps')
    map_file = models.FileField(upload_to='master_plans/')
    description = models.CharField(max_length=255)

class Interaction(BaseModel):
    listing = models.ForeignKey(Listing, on_delete=models.CASCADE)
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='interactions')
    interaction_type = models.CharField(max_length=10)

class Favorite(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='favorites', verbose_name="المستخدم")
    listing = models.ForeignKey(Listing, on_delete=models.CASCADE, related_name='favorites', verbose_name="العقار")
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        verbose_name = "مفضل"
        verbose_name_plural = "المفضلة"
        unique_together = ('user', 'listing')

# --- 5. الإعلانات المميزة والترويجية ---
class Promotion(models.Model):
    class PromoType(models.TextChoices):
        PROJECT = 'PROJECT', 'مشروع عقاري'
        SERVICE = 'SERVICE', 'خدمة'
        GENERAL = 'GENERAL', 'إعلان عام'
        LISTING = 'LISTING', 'إعلان VIP'
    
    master_plan = models.ImageField(upload_to='promotions/master_plans/', null=True, blank=True)
    title = models.CharField(max_length=200)
    subtitle = models.CharField(max_length=150, blank=True, null=True)
    slug = models.SlugField(unique=True, blank=True, null=True, allow_unicode=True)
    promo_type = models.CharField(max_length=20, choices=PromoType.choices, default=PromoType.GENERAL)
    developer_logo = models.ImageField(upload_to='promotions/logos/', null=True, blank=True)
    cover_image = models.ImageField(upload_to='promotions/covers/')
    video = models.FileField(upload_to='promotions/videos/', storage=VideoMediaCloudinaryStorage(), null=True, blank=True)
    details_video = models.FileField(upload_to='promotions/details_videos/', storage=VideoMediaCloudinaryStorage(), null=True, blank=True)
    youtube_url = models.URLField(null=True, blank=True, verbose_name="رابط فيديو يوتيوب")
    video_url = models.URLField(null=True, blank=True)
    target_listing = models.ForeignKey(Listing, on_delete=models.CASCADE, null=True, blank=True, related_name='promotions')
    description = models.TextField(blank=True)
    developer_name = models.CharField(max_length=100, blank=True, null=True)
    payment_system = models.TextField(blank=True, null=True)
    delivery_date = models.CharField(max_length=50, blank=True, null=True)
    project_features = models.TextField(blank=True, null=True)
    price_start_from = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    location_url = models.URLField(blank=True, null=True)
    latitude = models.DecimalField(max_digits=10, decimal_places=8, null=True, blank=True)
    longitude = models.DecimalField(max_digits=10, decimal_places=8, null=True, blank=True)
    phone_number = models.CharField(max_length=20, blank=True)
    whatsapp_number = models.CharField(max_length=20, blank=True)
    is_active = models.BooleanField(default=True)
    display_order = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    address = models.CharField(max_length=255, blank=True, null=True, verbose_name="العنوان النصي")
    views_count = models.PositiveIntegerField(default=0, verbose_name="عدد المشاهدات", db_index=True)
    clicks_count = models.PositiveIntegerField(default=0, verbose_name="عدد النقرات")
    whatsapp_clicks = models.PositiveIntegerField(default=0, verbose_name="نقرات الواتساب", db_index=True)
    call_clicks = models.PositiveIntegerField(default=0, verbose_name="نقرات الاتصال")

    def save(self, *args, **kwargs):
        if not self.slug: 
            self.slug = slugify(self.title, allow_unicode=True) + f"-{generate_ref()}"
        # شلنا كود الضغط من هنا
        if self.youtube_url and self.video:
            self.video = None
        super().save(*args, **kwargs)

class PromotionImage(models.Model):
    promotion = models.ForeignKey(Promotion, on_delete=models.CASCADE, related_name='gallery')
    image = models.ImageField(upload_to='promotions/gallery/')
    def save(self, *args, **kwargs):
        # شلنا كود الضغط من هنا
        super().save(*args, **kwargs)

class Transformation(models.Model):
    promotion = models.ForeignKey(Promotion, on_delete=models.CASCADE, related_name='transformations')
    before_image = models.ImageField(upload_to='promotions/before/', verbose_name="صورة قبل")
    after_image = models.ImageField(upload_to='promotions/after/', verbose_name="صورة بعد")
    title = models.CharField(max_length=100, blank=True, verbose_name="عنوان (مثال: الريسبشن)")

class PromotionUnit(models.Model):
    promotion = models.ForeignKey(Promotion, on_delete=models.CASCADE, related_name='units')
    linked_listing = models.ForeignKey('Listing', on_delete=models.CASCADE, null=True, blank=True)
    custom_title = models.CharField(max_length=100, blank=True)
    price = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True, verbose_name="السعر")
    image = models.ImageField(upload_to='promotions/units/', null=True, blank=True, verbose_name="صورة الوحدة")
    def __str__(self):
        if self.linked_listing: return self.custom_title or self.linked_listing.title
        return self.custom_title or "وحدة غير مرتبطة"

class AnalyticsLog(models.Model):
    EVENT_TYPES = [
        ('VIEW_LISTING', 'مشاهدة عقار'), ('VIEW_PROMO', 'مشاهدة إعلان'),
        ('CLICK_PROMO', 'ضغط على الإعلان'), ('CLICK_WHATSAPP', 'ضغط واتساب'),
        ('CLICK_CALL', 'ضغط اتصال'), ('SEARCH', 'بحث'),
    ]
    event_type = models.CharField(max_length=20, choices=EVENT_TYPES, verbose_name="نوع الحدث")
    listing = models.ForeignKey(Listing, on_delete=models.CASCADE, null=True, blank=True, verbose_name="العقار")
    promotion = models.ForeignKey(Promotion, on_delete=models.CASCADE, null=True, blank=True, verbose_name="الإعلان")
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="المستخدم")
    ip_address = models.GenericIPAddressField(null=True, blank=True, verbose_name="IP الزائر")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="التوقيت", db_index=True)

    class Meta:
        verbose_name = "سجل التحليلات"
        verbose_name_plural = "سجلات التحليلات"
        ordering = ['-created_at']

@receiver(post_save, sender=User)
def sync_user_data_to_listings(sender, instance, created, **kwargs):
    if not created:
        Listing.objects.filter(agent=instance).update(
            owner_phone=instance.phone_number,
            owner_name=f"{instance.first_name} {instance.last_name}".strip() or instance.username
        )


# --- 6. جداول التنازلات وبيانات العملاء الباحثين ---

# الجدول الأول: ده اللي بيتخزن فيه التنازلات اللي الإدارة بترفعها
class Waiver(models.Model):
    district = models.CharField(max_length=100, verbose_name="الحي")
    neighborhood = models.CharField(max_length=100, verbose_name="المجاورة")
    plot_number = models.CharField(max_length=100, verbose_name="رقم القطعة")
    procedure = models.CharField(max_length=255, verbose_name="الإجراء")
    committee_number = models.CharField(max_length=100, verbose_name="رقم اللجنة")
    procedure_date = models.CharField(max_length=50, null=True, blank=True, verbose_name="تاريخ الإجراء")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "تنازل"
        verbose_name_plural = "التنازلات"
        unique_together = ('district', 'neighborhood', 'plot_number')

    def __str__(self):
        return f"قطعة {self.plot_number} - {self.neighborhood} - {self.district}"

# الجدول التاني: ده "الكنز" اللي هيسجل أي حد يبحث في الصفحة
class WaiverLead(models.Model):
    phone_number = models.CharField(max_length=20, verbose_name="رقم الفون")
    full_name = models.CharField(max_length=150, verbose_name="الاسم")
    plot_number = models.CharField(max_length=100, verbose_name="رقم القطعة")
    neighborhood = models.CharField(max_length=100, verbose_name="المجاورة")
    district = models.CharField(max_length=100, verbose_name="الحي")
    
    STATUS_CHOICES = [('Success', 'تم التنازل'), ('Pending', 'قيد الانتظار')]
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, verbose_name="حالة التنازل")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "بحث عميل (ليد)"
        verbose_name_plural = "سجل بحث العملاء"

    def __str__(self):
        return f"{self.full_name} - {self.phone_number}"