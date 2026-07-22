from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    RegisterView, CustomAuthToken, UserProfileView, NotificationViewSet, 
    UpdateFCMTokenView, UserViewSet, contact_info,
)

router = DefaultRouter()
router.register(r'notifications', NotificationViewSet, basename='notification')
router.register(r'users', UserViewSet, basename='users')

urlpatterns = [
    path('register/', RegisterView.as_view(), name='register'),
    path('login/', CustomAuthToken.as_view(), name='login'),
    path('profile/', UserProfileView.as_view(), name='profile'),
    path('update-fcm/', UpdateFCMTokenView.as_view(), name='update-fcm'),
    path('contact-info/', contact_info, name='contact-info'), 
    path('', include(router.urls)),
]