from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db.models import Q
from django.shortcuts import get_object_or_404
from .models import ChatRoom, Message
from .serializers import ChatRoomSerializer, MessageSerializer
from .utils import pusher_client
from aqar.models import Listing  # تأكد من المسار
from rest_framework.views import APIView

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
        channel_name = f'private-chat_{room.id}'
        event_name = 'new_message'
        
        # بنجهز شكل الداتا اللي هتروح للفرونت إند
        data = MessageSerializer(message, context={'request': self.request}).data
        
        try:
            pusher_client.trigger(channel_name, event_name, data)
        except Exception as e:
            # لو Pusher فيه مشكلة، الرسالة اتحفظت خلاص بس بنطبع الخطأ عشان نعرفه
            print(f"Pusher Error: {e}")

class MarkMessagesAsReadView(APIView):
    """
    تحديث حالة الرسائل إلى "تمت القراءة" عند فتح المستخدم للمحادثة
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, room_id):
        room = get_object_or_404(ChatRoom, id=room_id)
        
        # التأكد إن اليوزر ده طرف في المحادثة
        if request.user not in [room.buyer, room.seller]:
            return Response({"detail": "غير مصرح لك"}, status=status.HTTP_403_FORBIDDEN)

        # هنجيب الرسايل اللي مبعوتة "من الطرف التاني" ولسه متقرتش
        unread_messages = room.messages.exclude(sender=request.user).filter(is_read=False)
        
        # نحدثهم كلهم مرة واحدة
        updated_count = unread_messages.update(is_read=True)

        # لو فعلاً كان في رسايل اتحدثت، نبعت إشعار لحظي بـ Pusher للطرف التاني
        if updated_count > 0:
            channel_name = f'private-chat_{room.id}'
            event_name = 'messages_read'
            
            try:
                # بنبعت الـ ID بتاع اليوزر اللي قرأ الرسايل عشان الفرونت إند يعرف
                pusher_client.trigger(channel_name, event_name, {'read_by': request.user.id})
            except Exception as e:
                print(f"Pusher Error: {e}")

        return Response({"detail": "تم تحديث حالة القراءة", "updated_count": updated_count}, status=status.HTTP_200_OK)

class PusherAuthView(APIView):
    """
    التصريح للفرونت إند بالاستماع لقنوات Pusher الخاصة
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        # Pusher بيبعت المتغيرين دول أوتوماتيك من الفرونت إند
        channel_name = request.data.get('channel_name')
        socket_id = request.data.get('socket_id')

        if not channel_name or not socket_id:
            return Response({"detail": "بيانات ناقصة"}, status=status.HTTP_400_BAD_REQUEST)

        # هنتأكد إن القناة دي تابعة للشات بتاعنا
        if channel_name.startswith('private-chat_'):
            # بنستخرج رقم الغرفة من اسم القناة (مثلاً private-chat_15)
            room_id = channel_name.split('private-chat_')[1]
            room = get_object_or_404(ChatRoom, id=room_id)

            # 🚨 الأمان الحقيقي: هل اليوزر ده هو البائع أو المشتري في الغرفة دي؟
            if request.user not in [room.buyer, room.seller]:
                return Response({"detail": "غير مصرح لك بدخول هذه الغرفة!"}, status=status.HTTP_403_FORBIDDEN)

            # لو هو فعلاً طرف في المحادثة، هنمضي الطلب ونرجعله التصريح المشفر
            auth = pusher_client.authenticate(
                channel=channel_name,
                socket_id=socket_id
            )
            return Response(auth, status=status.HTTP_200_OK)

        return Response({"detail": "قناة غير صالحة"}, status=status.HTTP_400_BAD_REQUEST)