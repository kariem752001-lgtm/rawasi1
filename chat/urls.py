from django.urls import path
from . import views

urlpatterns = [
    path('rooms/', views.ChatRoomListView.as_view(), name='room-list'),
    path('rooms/start/<int:listing_id>/', views.StartOrGetChatRoomView.as_view(), name='start-room'),
    path('rooms/<int:room_id>/messages/', views.MessageListCreateView.as_view(), name='room-messages'),
    path('rooms/<int:room_id>/read/', views.MarkMessagesAsReadView.as_view(), name='mark-messages-read'),
    path('pusher/auth/', views.PusherAuthView.as_view(), name='pusher-auth'),
]