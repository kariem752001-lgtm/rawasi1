from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    ListingViewSet, GovernorateViewSet, CityViewSet, 
    MajorZoneViewSet, SubdivisionViewSet, CategoryViewSet, AdminDeleteAllWaiversView,
    FavoriteViewSet, PromotionViewSet , track_analytics, get_dashboard_stats, AdminGeographyView,
    CloudinarySignatureView # 👈 استيراد الـ View الجديد
)
from .views import WaiverSearchView, AdminUploadWaiversView, AdminExportWaiverLeadsView, AdminWaiverLeadsListView, AdminDeleteWaiverLeadView
from .views import AdminDashboardStatsView, SmartTrackEventView, AdminListingsView, AdminUpdateListingStatusView
from .views import AdminPromotionsView, AdminTogglePromotionView, AdminCreatePromotionView, AdminDeleteGeographyView
from aqar_core.views import AdminUsersListView, AdminBroadcastNotificationView
from aqar_core.views import AdminUsersListView, AdminBroadcastNotificationView, AdminUserDetailView
from aqar_core.views import contact_info

router = DefaultRouter()
router.register(r'listings', ListingViewSet, basename='listing')
router.register(r'promotions', PromotionViewSet, basename='promotion')
router.register(r'governorates', GovernorateViewSet)
router.register(r'cities', CityViewSet)
router.register(r'major-zones', MajorZoneViewSet)
router.register(r'subdivisions', SubdivisionViewSet)
router.register(r'categories', CategoryViewSet)
router.register(r'favorites', FavoriteViewSet, basename='favorite')

urlpatterns = [
    path('', include(router.urls)),
    # 🚀 المسار الجديد لرفع الصور بأمان
    path('upload-signature/', CloudinarySignatureView.as_view(), name='upload-signature'),
    path('contact-info/', contact_info, name='contact-info'), # 👈 ضيف السطر ده هنا
    path('analytics/track/', track_analytics, name='track-analytics'),
    path('analytics/dashboard/', get_dashboard_stats, name='dashboard-stats'),
    path('admin-dashboard/stats/', AdminDashboardStatsView.as_view(), name='admin-stats'),
    path('track-event/smart/', SmartTrackEventView.as_view(), name='smart-track'),
    path('admin-dashboard/listings/', AdminListingsView.as_view(), name='admin-listings'),
    path('admin-dashboard/listings/<int:pk>/status/', AdminUpdateListingStatusView.as_view(), name='admin-listing-status'),
    path('admin-dashboard/promotions/', AdminPromotionsView.as_view(), name='admin-promos'),
    path('admin-dashboard/promotions/<int:pk>/toggle/', AdminTogglePromotionView.as_view(), name='admin-promo-toggle'),
    path('admin-dashboard/promotions/add/', AdminCreatePromotionView.as_view(), name='admin-promo-add'),
    path('admin-dashboard/geography/', AdminGeographyView.as_view(), name='admin-geography'),
    path('admin-dashboard/geography/delete/', AdminDeleteGeographyView.as_view(), name='admin-geography-delete'),
    path('admin-dashboard/users/', AdminUsersListView.as_view(), name='admin-users'),
    path('admin-dashboard/broadcast/', AdminBroadcastNotificationView.as_view(), name='admin-broadcast'),
    path('admin-dashboard/users/<int:user_id>/', AdminUserDetailView.as_view(), name='admin-user-detail'),
    path('waivers/search/', WaiverSearchView.as_view(), name='waiver-search'),
    path('admin-dashboard/waivers/upload/', AdminUploadWaiversView.as_view(), name='admin-upload-waivers'),
    path('admin-dashboard/waivers/export/', AdminExportWaiverLeadsView.as_view(), name='admin-export-waivers'),
    path('admin-dashboard/waivers/leads/', AdminWaiverLeadsListView.as_view(), name='admin-waiver-leads-list'),
    path('admin-dashboard/waivers/leads/<int:pk>/', AdminDeleteWaiverLeadView.as_view(), name='admin-delete-waiver-lead'),
    path('admin-dashboard/waivers/delete-all/', AdminDeleteAllWaiversView.as_view(), name='admin-delete-all-waivers'),
]