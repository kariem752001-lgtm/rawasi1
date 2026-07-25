from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db.models import Q
from django.shortcuts import get_object_or_404
from .models import ChatRoom, Message
from .serializers import ChatRoomSerializer, MessageSerializer
from .utils import pusher_client
from aqar.models import Listing  
from rest_framework.views import APIView

class ChatRoomListView(generics.ListAPIView):
    serializer_class = ChatRoomSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        return ChatRoom.objects.filter(
            Q(buyer=user) | Q(seller=user)
        ).select_related('listing', 'buyer', 'seller').prefetch_related('messages')


class StartOrGetChatRoomView(generics.GenericAPIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, listing_id):
        listing = get_object_or_404(Listing, id=listing_id)
        buyer = request.user
        seller = listing.agent
        if not seller:
            return Response({"detail": "هذا الإعلان غير مرتبط بمالك محدد."}, status=status.HTTP_400_BAD_REQUEST)

        if str(buyer.id) == str(seller.id):
            return Response({"detail": "لا يمكنك بدء محادثة مع نفسك!"}, status=status.HTTP_400_BAD_REQUEST)

        room, created = ChatRoom.objects.get_or_create(
            listing=listing, buyer=buyer, seller=seller
        )
        serializer = ChatRoomSerializer(room, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)


class MessageListCreateView(generics.ListCreateAPIView):
    serializer_class = MessageSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = None

    def get_queryset(self):
        room_id = self.kwargs['room_id']
        return Message.objects.filter(room_id=room_id).order_by('created_at')

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        serializer = self.get_serializer(queryset, many=True)
        data = serializer.data
        for msg in data:
            msg['is_me'] = str(msg.get('sender')) == str(request.user.id)
        return Response(data)

    def perform_create(self, serializer):
        room = get_object_or_404(ChatRoom, id=self.kwargs['room_id'])
        message = serializer.save(sender=self.request.user, room=room)
        
        room.updated_at = message.created_at
        room.save(update_fields=['updated_at'])

        channel_name = f'private-chat_{room.id}'
        
        data = {
            'id': message.id,
            'content': message.content,
            'created_at': message.created_at.isoformat(),
            'is_read': message.is_read,
            'is_delivered': getattr(message, 'is_delivered', False), # تأمين لو الحقل مش موجود
            'sender': self.request.user.id 
        }
        
        # 🚀 تأمين مقارنة الـ IDs بتحويلهم لنصوص عشان ميفوتش المستلم
        current_id = str(self.request.user.id)
        buyer_id = str(room.buyer.id)
        receiver = room.seller if current_id == buyer_id else room.buyer

        print(f"🔥 DEBUG BACKEND: Sender={current_id}, Receiver={receiver.id}")

        try:
            pusher_client.trigger(channel_name, 'new_message', data)
        except Exception as e:
            print(f"Pusher Chat Error: {e}")

        if receiver:
            try:
                global_channel = f'private-user_{receiver.id}'
                print(f"🔥 DEBUG BACKEND: Triggering Notification to {global_channel}")
                pusher_client.trigger(global_channel, 'new_message_notification', data)
            except Exception as e:
                print(f"Pusher Global Error: {e}")


class MarkMessagesAsReadView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, room_id):
        room = get_object_or_404(ChatRoom, id=room_id)
        
        if str(request.user.id) not in [str(room.buyer.id), str(room.seller.id)]:
            return Response({"detail": "غير مصرح لك"}, status=status.HTTP_403_FORBIDDEN)

        unread_messages = room.messages.exclude(sender=request.user).filter(is_read=False)
        updated_count = unread_messages.update(is_read=True)

        if updated_count > 0:
            channel_name = f'private-chat_{room.id}'
            try:
                pusher_client.trigger(channel_name, 'messages_read', {'read_by': request.user.id})
            except Exception as e:
                pass

        return Response({"detail": "تم", "updated_count": updated_count}, status=status.HTTP_200_OK)


class MarkMessageAsDeliveredView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, message_id):
        message = get_object_or_404(Message, id=message_id)
        
        if str(message.sender_id) != str(request.user.id):
            if hasattr(message, 'is_delivered') and not message.is_delivered:
                message.is_delivered = True
                message.save(update_fields=['is_delivered'])
                
                channel_name = f'private-chat_{message.room.id}'
                try:
                    pusher_client.trigger(channel_name, 'message_delivered', {'message_id': message.id})
                    print(f"🔥 DEBUG BACKEND: Delivered event sent to {channel_name}")
                except Exception as e:
                    print(f"Pusher Error: {e}")
            else:
                 print("🔥 DEBUG BACKEND: is_delivered not found in DB or already delivered")
                
        return Response({"detail": "Delivered"}, status=status.HTTP_200_OK)


class PusherAuthView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        channel_name = request.data.get('channel_name')
        socket_id = request.data.get('socket_id')

        if not channel_name or not socket_id:
            return Response({"detail": "بيانات ناقصة"}, status=status.HTTP_400_BAD_REQUEST)

        if 'undefined' in channel_name or 'null' in channel_name:
            return Response({"detail": "قناة غير صالحة بسبب غياب الـ ID"}, status=status.HTTP_400_BAD_REQUEST)

        if channel_name.startswith('private-chat_'):
            room_id = channel_name.split('private-chat_')[1]
            room = get_object_or_404(ChatRoom, id=room_id)
            if str(request.user.id) not in [str(room.buyer_id), str(room.seller_id)]:
                return Response({"detail": "غير مصرح"}, status=status.HTTP_403_FORBIDDEN)
                
        elif channel_name.startswith('private-user_'):
            user_id = channel_name.split('private-user_')[1]
            if str(request.user.id) != str(user_id):
                return Response({"detail": "غير مصرح"}, status=status.HTTP_403_FORBIDDEN)

        try:
            auth = pusher_client.authenticate(channel=channel_name, socket_id=socket_id)
            return Response(auth, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class UnreadMessageCountView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        rooms = ChatRoom.objects.filter(Q(buyer=user) | Q(seller=user))
        
        unread_count = Message.objects.filter(
            room__in=rooms, 
            is_read=False
        ).exclude(sender=user).count()

        # 🚀 السحر هنا: بنجبر السيرفر يبعت الـ ID الحقيقي للمتصفح عشان يشغل بيه البوشر صح
        return Response({
            "unread_count": unread_count,
            "user_id": user.id 
        }, status=status.HTTP_200_OK)