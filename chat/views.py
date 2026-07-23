from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db.models import Q
from django.shortcuts import get_object_or_404
from .models import ChatRoom, Message
from .serializers import ChatRoomSerializer, MessageSerializer
from .utils import pusher_client
from aqar.models import Listing  # تأكد من المسار

class ChatRoomListView(generics.ListAPIView):
    """
    جلب كل المحادثات الخاصة بالمستخدم (سواء كان بائع أو مشتري)
    """
    serializer_class = ChatRoomSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        return ChatRoom.objects.filter(Q(buyer=user) | Q(seller=user))


class StartOrGetChatRoomView(generics.GenericAPIView):
    """
    لو المشتري ضغط "تواصل مع البائع"، بنفتح الغرفة لو موجودة، أو نكريتها لو أول مرة
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, listing_id):
        listing = get_object_or_404(Listing, id=listing_id)
        buyer = request.user
        seller = listing.owner # ⚠️ غيّر كلمة owner لاسم حقل اليوزر في موديل الإعلانات عندك لو مختلف

        if buyer == seller:
            return Response({"detail": "لا يمكنك بدء محادثة مع نفسك!"}, status=status.HTTP_400_BAD_REQUEST)

        room, created = ChatRoom.objects.get_or_create(
            listing=listing, buyer=buyer, seller=seller
        )
        serializer = ChatRoomSerializer(room, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)


class MessageListCreateView(generics.ListCreateAPIView):
    """
    جلب رسائل غرفة معينة وإرسال رسالة جديدة (مع تفعيل Pusher)
    """
    serializer_class = MessageSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        room_id = self.kwargs['room_id']
        return Message.objects.filter(room_id=room_id)

    def perform_create(self, serializer):
        room = get_object_or_404(ChatRoom, id=self.kwargs['room_id'])
        
        # 1. حفظ الرسالة في قاعدة البيانات
        message = serializer.save(sender=self.request.user, room=room)
        
        # تحديث وقت الغرفة عشان تطلع فوق في القائمة
        room.updated_at = message.created_at
        room.save()

        # 2. إرسال الرسالة عبر Pusher (السحر اللحظي ✨)
        channel_name = f'chat_{room.id}'
        event_name = 'new_message'
        
        # بنجهز شكل الداتا اللي هتروح للفرونت إند
        data = MessageSerializer(message, context={'request': self.request}).data
        
        try:
            pusher_client.trigger(channel_name, event_name, data)
        except Exception as e:
            # لو Pusher فيه مشكلة، الرسالة اتحفظت خلاص بس بنطبع الخطأ عشان نعرفه
            print(f"Pusher Error: {e}")