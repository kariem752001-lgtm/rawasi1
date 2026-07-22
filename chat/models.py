from django.db import models
from django.conf import settings
from aqar.models import Listing  # تأكد إن ده مسار موديل الإعلانات بتاعك صح

class ChatRoom(models.Model):
    listing = models.ForeignKey(Listing, on_delete=models.CASCADE, related_name='chat_rooms', verbose_name="الإعلان")
    buyer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='buyer_rooms', verbose_name="المشتري")
    seller = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='seller_rooms', verbose_name="البائع")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "غرفة محادثة"
        verbose_name_plural = "غرف المحادثة"
        unique_together = ('listing', 'buyer', 'seller')
        ordering = ['-updated_at']

    def __str__(self):
        return f"شات: {self.listing.title} | {self.buyer.first_name} مع {self.seller.first_name}"


class Message(models.Model):
    room = models.ForeignKey(ChatRoom, on_delete=models.CASCADE, related_name='messages', verbose_name="الغرفة")
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, verbose_name="المرسل")
    content = models.TextField(verbose_name="محتوى الرسالة")
    
    # حالات الرسالة (زي الواتساب)
    is_delivered = models.BooleanField(default=False, verbose_name="تم الاستلام (صحين)")
    is_read = models.BooleanField(default=False, verbose_name="تمت القراءة (صحين أزرق)")
    
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="وقت الإرسال (صح واحدة)")

    class Meta:
        verbose_name = "رسالة"
        verbose_name_plural = "الرسائل"
        ordering = ['created_at']  # من الأقدم للأحدث

    def __str__(self):
        return f"رسالة من {self.sender.first_name} - الغرفة {self.room.id}"