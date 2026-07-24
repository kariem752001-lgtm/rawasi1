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
    serializer_class = ChatRoomSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        # 🚀 ضفنا prefetch عشان الباك إند ميستهلكش موارد السيرفر
        return ChatRoom.objects.filter(
            Q(buyer=user) | Q(seller=user)
        ).select_related('listing', 'buyer', 'seller').prefetch_related('messages')
        

class StartOrGetChatRoomView(generics.GenericAPIView):
    """
    لو المشتري ضغط "تواصل مع البائع"، بنفتح الغرفة لو موجودة، أو نكريتها لو أول مرة
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, listing_id):
        listing = get_object_or_404(Listing, id=listing_id)
        buyer = request.user
        seller = listing.agent
        if not seller:
            return Response({"detail": "هذا الإعلان غير مرتبط بمالك محدد."}, status=status.HTTP_400_BAD_REQUEST) # ⚠️ غيّر كلمة owner لاسم حقل اليوزر في موديل الإعلانات عندك لو مختلف

        if buyer == seller:
            return Response({"detail": "لا يمكنك بدء محادثة مع نفسك!"}, status=status.HTTP_400_BAD_REQUEST)

        room, created = ChatRoom.objects.get_or_create(
            listing=listing, buyer=buyer, seller=seller
        )
        serializer = ChatRoomSerializer(room, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)


class MessageListCreateView(generics.ListCreateAPIView):
    serializer_class = MessageSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        room_id = self.kwargs['room_id']
        return Message.objects.filter(room_id=room_id)

    def perform_create(self, serializer):
        room = get_object_or_404(ChatRoom, id=self.kwargs['room_id'])
        
        # 1. حفظ الرسالة
        message = serializer.save(sender=self.request.user, room=room)
        
        # تحديث وقت الغرفة
        room.updated_at = message.created_at
        room.save()

        # 2. إرسال الرسالة للغرفة (عشان اللي فاتح الشات)
        channel_name = f'private-chat_{room.id}'
        event_name = 'new_message'
        data = MessageSerializer(message, context={'request': self.request}).data
        
        # 🚀 تحديد الطرف الآخر (المستلم) عشان نبعتله إشعار عام
        receiver = room.seller if self.request.user == room.buyer else room.buyer

        try:
            pusher_client.trigger(channel_name, event_name, data)
            
            # 🚀 3. إرسال إشعار لحظي للقناة العامة بتاعت المستلم (عشان العداد ينور في الـ Navbar)
            if receiver:
                global_channel = f'private-user_{receiver.id}'
                pusher_client.trigger(global_channel, 'new_message_notification', data)
                
        except Exception as e:
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
    permission_classes = [IsAuthenticated]

    def post(self, request):
        channel_name = request.data.get('channel_name')
        socket_id = request.data.get('socket_id')

        if not channel_name or not socket_id:
            return Response({"detail": "بيانات ناقصة"}, status=status.HTTP_400_BAD_REQUEST)

        # 🚀 فحص تصريح غرفة الشات
        if channel_name.startswith('private-chat_'):
            room_id = channel_name.split('private-chat_')[1]
            room = get_object_or_404(ChatRoom, id=room_id)
            if request.user not in [room.buyer, room.seller]:
                return Response({"detail": "غير مصرح لك بدخول هذه الغرفة!"}, status=status.HTTP_403_FORBIDDEN)
                
        # 🚀 فحص تصريح القناة العامة لليوزر (لإشعارات الـ Navbar)
        elif channel_name.startswith('private-user_'):
            user_id = channel_name.split('private-user_')[1]
            if str(request.user.id) != str(user_id):
                return Response({"detail": "غير مصرح لك بالاستماع لإشعارات مستخدم آخر!"}, status=status.HTTP_403_FORBIDDEN)
        
        else:
            return Response({"detail": "قناة غير صالحة"}, status=status.HTTP_400_BAD_REQUEST)

        # لو كل حاجة تمام، نمضي الطلب
        auth = pusher_client.authenticate(
            channel=channel_name,
            socket_id=socket_id
        )
        return Response(auth, status=status.HTTP_200_OK)


# 🚀 الكلاس الجديد اللي هيحل مشكلة الـ 404 (ضيفيه في آخر الملف)
class UnreadMessageCountView(APIView):
    """
    إرجاع عدد الرسائل غير المقروءة للمستخدم لعرضها في شريط التنقل (Navbar)
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        
        # بنجيب كل الغرف اللي اليوزر طرف فيها
        rooms = ChatRoom.objects.filter(Q(buyer=user) | Q(seller=user))
        
        # بنعد كل الرسايل اللي في الغرف دي، بشرط إنها تكون مش مقروءة ومبعوتة من حد تاني
        unread_count = Message.objects.filter(
            room__in=rooms, 
            is_read=False
        ).exclude(sender=user).count()

        return Response({"unread_count": unread_count}, status=status.HTTP_200_OK)