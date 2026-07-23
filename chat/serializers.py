from rest_framework import serializers
from .models import ChatRoom, Message
from .utils import validate_no_phone_numbers

class MessageSerializer(serializers.ModelSerializer):
    # حقل إضافي عشان الفرونت إند يعرف يفرق بين رسائل اليوزر والرسائل التانية
    is_me = serializers.SerializerMethodField()
    sender_name = serializers.CharField(source='sender.first_name', read_only=True)

    class Meta:
        model = Message
        fields = ['id', 'room', 'sender', 'sender_name', 'content', 'is_delivered', 'is_read', 'created_at', 'is_me']
        read_only_fields = ['room', 'sender', 'is_delivered', 'is_read']

    def get_is_me(self, obj):
        request = self.context.get('request')
        if request and hasattr(request, 'user'):
            return obj.sender == request.user
        return False

    def validate_content(self, value):
        # تشغيل دالة منع الأرقام هنا قبل الحفظ
        validate_no_phone_numbers(value)
        return value


class ChatRoomSerializer(serializers.ModelSerializer):
    listing_title = serializers.CharField(source='listing.title', read_only=True)
    other_user = serializers.SerializerMethodField()
    last_message = serializers.SerializerMethodField()

    class Meta:
        model = ChatRoom
        fields = ['id', 'listing', 'listing_title', 'other_user', 'last_message', 'updated_at']

    def get_other_user(self, obj):
        # بنرجع بيانات الطرف التاني في المحادثة
        request = self.context.get('request')
        if not request:
            return None
        
        other = obj.seller if request.user == obj.buyer else obj.buyer
        return {
            'id': other.id,
            'name': other.first_name,
        }

    def get_last_message(self, obj):
        # بنجيب آخر رسالة عشان تظهر في قائمة المحادثات من بره
        last_msg = obj.messages.last()
        if last_msg:
            return {
                'content': last_msg.content,
                'created_at': last_msg.created_at,
                'is_read': last_msg.is_read
            }
        return None