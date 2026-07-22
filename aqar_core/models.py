from django.db import models
from django.contrib.auth.models import AbstractUser
from django.conf import settings

class BaseModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإنشاء", db_index=True)
    updated_at = models.DateTimeField(auto_now=True, verbose_name="آخر تحديث")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.SET_NULL, 
        null=True, blank=True, 
        verbose_name="بواسطة",
        related_name="%(app_label)s_%(class)s_created_by"
    )
    class Meta: abstract = True

class User(AbstractUser):
    phone_number = models.CharField(max_length=20, unique=True, null=True, blank=True, verbose_name="رقم الهاتف")
    whatsapp_link = models.CharField(max_length=255, blank=True, verbose_name="رابط الواتساب")
    is_agent = models.BooleanField(default=False, verbose_name="هل هو موظف؟")
    interests = models.TextField(null=True, blank=True, verbose_name="الاهتمامات")

    CLIENT_TYPES = [('Buyer', 'مشترِي'), ('Seller', 'بائع'), ('Investor', 'مستثمر'), ('Marketer', 'مسوق')]
    client_type = models.CharField(max_length=10, choices=CLIENT_TYPES, default='Buyer', db_index=True, verbose_name="نوع العميل")
    
    interested_in_rent = models.BooleanField(default=False, verbose_name="مهتم بالإيجار")
    interested_in_buy = models.BooleanField(default=True, verbose_name="مهتم بالشراء")

    fcm_token = models.TextField(null=True, blank=True, verbose_name="FCM Token")
    is_owner = models.BooleanField(
        default=False, 
        verbose_name="مالك الموقع",
        help_text="تفعيل هذا الخيار يمنع حذف هذا الحساب نهائياً حتى من قبل المديرين الآخرين."
    )

class Notification(BaseModel):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications', verbose_name="المستخدم", db_index=True)
    title = models.CharField(max_length=255, verbose_name="عنوان الإشعار")
    message = models.TextField(verbose_name="نص الرسالة")
    is_read = models.BooleanField(default=False, verbose_name="تمت القراءة؟", db_index=True)
    
    TYPE_CHOICES = [('System', 'إداري'), ('Listing', 'عقار'), ('Offer', 'عرض')]
    notification_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default='System', db_index=True)

    class Meta:
        verbose_name = "إشعار"
        verbose_name_plural = "الإشعارات"
        ordering = ['-created_at']

    def __str__(self): return f"{self.title} - {self.user.username}"

class SiteSetting(models.Model):
    key = models.CharField(max_length=100, unique=True, verbose_name="المفتاح (كود الإعداد)") 
    value = models.CharField(max_length=500, verbose_name="القيمة")            

    class Meta:
        verbose_name = "إعداد عام"
        verbose_name_plural = "إعدادات الموقع"
    def __str__(self): return self.key

class Announcement(models.Model):
    AUDIENCE_CHOICES = [
        ('ALL', 'الكل'), ('Buyer', 'المشترين فقط'), ('Seller', 'الملاك/البائعين فقط'), ('Broker', 'السماسرة فقط'),
    ]
    title = models.CharField(max_length=200, verbose_name="عنوان الرسالة")
    message = models.TextField(verbose_name="نص الرسالة")
    target_audience = models.CharField(max_length=20, choices=AUDIENCE_CHOICES, default='ALL', verbose_name="الجمهور المستهدف")
    sent_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الإرسال")
    is_sent = models.BooleanField(default=False, verbose_name="تم الإرسال؟", editable=False) 

    def __str__(self): return self.title
    class Meta:
        verbose_name = "إرسال إشعار جماعي"
        verbose_name_plural = "📣 إرسال إشعارات جماعية"

class ContactInfo(models.Model):
    support_phone = models.CharField(max_length=20, default='01000000000', verbose_name="رقم الاتصال")
    whatsapp_number = models.CharField(max_length=20, default='20100000000', verbose_name="رقم الواتساب (بدون +)")
    
    class Meta:
        verbose_name = "إعدادات التواصل"
        verbose_name_plural = "إعدادات التواصل"

    def __str__(self): return "أرقام الدعم الفني"

    # ✅ حماية قوية: إجبار الداتا بيز على حفظ صف واحد فقط ID=1
    def save(self, *args, **kwargs):
        self.pk = 1
        super(ContactInfo, self).save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        pass # ✅ منع الحذف تماماً