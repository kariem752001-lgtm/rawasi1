import os
import time  # 👈 إضافة ضرورية
import cloudinary.utils  # 👈 إضافة ضرورية
from django.conf import settings
from rest_framework.views import APIView
from rest_framework import viewsets, permissions, filters, status
from rest_framework.authentication import TokenAuthentication, SessionAuthentication
from rest_framework.decorators import action, api_view, permission_classes, authentication_classes
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAdminUser, BasePermission, SAFE_METHODS
from django_filters.rest_framework import DjangoFilterBackend
from django.shortcuts import get_object_or_404
from django.db.models import Q, F,Sum
from django.utils.timezone import now
from datetime import timedelta
from .models import *
from .serializers import *
from .filters import ListingFilter
from rest_framework.parsers import MultiPartParser
from aqar_core.models import User 
from aqar_core.models import Notification
import pandas as pd
from django.http import HttpResponse
from .models import WaiverLead 
from rest_framework.parsers import MultiPartParser
from django.db.models import Exists, OuterRef
try:
    from aqar_core.fcm_manager import send_push_notification
except ImportError:
    def send_push_notification(*args, **kwargs): pass

class GovernorateViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Governorate.objects.all()
    serializer_class = GovernorateSerializer
    pagination_class = None

class CityViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = City.objects.all()
    serializer_class = CitySerializer
    pagination_class = None
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['governorate']

class MajorZoneViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = MajorZone.objects.all()
    serializer_class = MajorZoneSerializer
    pagination_class = None
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['city']

class SubdivisionViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Subdivision.objects.all()
    serializer_class = SubdivisionSerializer
    pagination_class = None
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['major_zone']

class CategoryViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    pagination_class = None
    permission_classes = [AllowAny] # 👈 إنت نسيت السطر ده يا هندسة! ضيفه هنا
    
    @action(detail=True, methods=['get'])
    def features(self, request, pk=None):
        category = self.get_object()
        serializer = FeatureSerializer(category.allowed_features.all(), many=True)
        return Response(serializer.data)

class IsOwnerOrReadOnly(BasePermission):
    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS: return True
        return obj.agent == request.user or request.user.is_staff

class ListingViewSet(viewsets.ModelViewSet):
    serializer_class = ListingSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = ListingFilter
    search_fields = ['title', 'description', 'reference_code']
    permission_classes = [permissions.IsAuthenticatedOrReadOnly, IsOwnerOrReadOnly]

    def get_queryset(self):
        user = self.request.user
        queryset = Listing.objects.select_related(
            'governorate', 'city', 'category', 'agent', 'major_zone', 'subdivision'
        ).prefetch_related(
            'images', 'features_values', 'features_values__feature' 
        ).order_by('-created_at')

        if user.is_authenticated:
            queryset = queryset.annotate(
                is_favorite_annotated=Exists(
                    Favorite.objects.filter(listing=OuterRef('pk'), user=user)
                )
            )

        if self.action in ['retrieve', 'update', 'partial_update', 'destroy']:
            if user.is_staff: pass 
            elif user.is_authenticated:
                queryset = queryset.filter(Q(status='Available') | Q(agent=user)).distinct()
            else: queryset = queryset.filter(status='Available')
        elif self.action == 'list':
            queryset = queryset.filter(status='Available')

        qp = self.request.query_params
        for key, value in qp.items():
            if not value or value == '0': continue
            
            if key.startswith('multi_feat_'):
                try:
                    ids_str = key.replace('multi_feat_', '')
                    feature_ids = ids_str.split('-')
                    value = value.strip()
                    lookup = 'regex' if value.isdigit() else 'icontains'
                    filter_kwargs = {
                        'features_values__feature_id__in': feature_ids,
                        f'features_values__value__{lookup}': fr'(^|\D){value}(\D|$)' if lookup == 'regex' else value
                    }
                    queryset = queryset.filter(**filter_kwargs).distinct()
                except: pass

            elif key.startswith('feat_'):
                try:
                    feature_id = key.split('_')[1]
                    queryset = queryset.filter(
                        features_values__feature_id=feature_id,
                        features_values__value__icontains=value.strip()
                    ).distinct()
                except: pass
        
        return queryset

    def perform_create(self, serializer):
        user = self.request.user
        status = 'Available' if user.is_staff else 'Pending'
        incoming_phone = serializer.validated_data.get('owner_phone', '')
        incoming_name = serializer.validated_data.get('owner_name', '')
        final_phone = incoming_phone if incoming_phone else user.phone_number
        final_name = incoming_name if incoming_name else f"{user.first_name} {user.last_name}".strip() or user.username
        serializer.save(agent=user, status=status, owner_phone=final_phone, owner_name=final_name)

    def perform_update(self, serializer):
        user = self.request.user
        if not user.is_staff: serializer.save(status='Pending')
        else: serializer.save()

    @action(detail=False, methods=['get'])
    def my_listings(self, request):
        if not request.user.is_authenticated: return Response({'detail': 'غير مصرح'}, status=401)
        listings = Listing.objects.filter(agent=request.user).select_related(
            'governorate', 'city', 'category'
        ).prefetch_related('images').order_by('-created_at')
        
        page = self.paginate_queryset(listings)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = self.get_serializer(listings, many=True)
        return Response(serializer.data)
   
    @action(detail=True, methods=['POST'], parser_classes=[MultiPartParser], url_path='upload-video')
    def upload_video(self, request, pk=None):
        listing = self.get_object()
        
        if listing.agent != request.user:
            return Response({"detail": "غير مصرح لك بتعديل هذا الإعلان."}, status=status.HTTP_403_FORBIDDEN)

        chunk = request.FILES.get('file')
        content_range = request.data.get('content_range')
        
        if not chunk or not content_range:
            return Response({"detail": "بيانات الملف غير مكتملة."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            range_info = content_range.split(' ')[1]
            byte_range, total_size = range_info.split('/')
            start_byte, end_byte = map(int, byte_range.split('-'))
            total_size = int(total_size)
        except Exception:
            return Response({"detail": "تنسيق content_range غير صحيح."}, status=status.HTTP_400_BAD_REQUEST)

        temp_dir = os.path.join(settings.MEDIA_ROOT, 'temp_videos')
        os.makedirs(temp_dir, exist_ok=True)
        file_path = os.path.join(temp_dir, f'listing_{listing.id}_video.mp4')

        with open(file_path, 'ab' if start_byte > 0 else 'wb') as f:
            f.seek(start_byte)
            f.write(chunk.read())

        if end_byte + 1 >= total_size:
            from .utils import trigger_youtube_upload ,_upload_task
            import threading
            
            thread = threading.Thread(
                target=_upload_task,
                args=(
                    file_path,
                    f"عقار رواسي: {listing.title}",
                    listing.description[:200] if listing.description else "إعلان عقاري",
                    listing
                )
            )
            thread.start()
                
            return Response({"status": "completed", "detail": "تم الرفع بنجاح."}, status=status.HTTP_200_OK)

        return Response({"status": "uploading", "detail": "جاري الرفع... "}, status=status.HTTP_206_PARTIAL_CONTENT)

class FavoriteViewSet(viewsets.GenericViewSet):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = FavoriteSerializer 
    def list(self, request):
        favorites = Favorite.objects.filter(user=request.user).select_related('listing', 'listing__city', 'listing__governorate').prefetch_related('listing__images')
        return Response(self.get_serializer(favorites, many=True).data)

    @action(detail=False, methods=['post'])
    def toggle(self, request):
        listing_id = request.data.get('listing_id')
        listing = get_object_or_404(Listing, pk=listing_id)
        fav, created = Favorite.objects.get_or_create(user=request.user, listing=listing)
        if not created: 
            fav.delete()
            return Response({'status': 'removed'})
        return Response({'status': 'added'})

class PromotionViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Promotion.objects.filter(is_active=True).order_by('display_order', '-created_at')
    serializer_class = PromotionSerializer
    permission_classes = [permissions.AllowAny]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['slug', 'promo_type', 'is_active']

@api_view(['POST'])
@authentication_classes([TokenAuthentication, SessionAuthentication])
@permission_classes([AllowAny])
def track_analytics(request):
    event_type = request.data.get('event_type')
    target_id = request.data.get('target_id')
    target_type = request.data.get('target_type')
    
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    ip = x_forwarded_for.split(',')[0] if x_forwarded_for else request.META.get('REMOTE_ADDR')

    log_event = 'VIEW_LISTING'
    if target_type == 'promotion':
        if event_type == 'VIEW': log_event = 'VIEW_PROMO'
        elif event_type == 'CLICK_DETAILS': log_event = 'CLICK_PROMO'
    
    if event_type == 'WHATSAPP': log_event = 'CLICK_WHATSAPP'
    elif event_type == 'CALL': log_event = 'CLICK_CALL'

    log = AnalyticsLog(event_type=log_event, ip_address=ip)
    if request.user.is_authenticated: log.user = request.user
    
    if target_type == 'listing':
        listing = get_object_or_404(Listing, id=target_id)
        log.listing = listing
        if event_type == 'VIEW': listing.views_count = F('views_count') + 1
        elif event_type == 'WHATSAPP': listing.whatsapp_clicks = F('whatsapp_clicks') + 1
        elif event_type == 'CALL': listing.call_clicks = F('call_clicks') + 1
        listing.save(update_fields=['views_count', 'whatsapp_clicks', 'call_clicks']) 

    elif target_type == 'promotion':
        promo = get_object_or_404(Promotion, id=target_id)
        log.promotion = promo
        if event_type == 'VIEW': promo.views_count = F('views_count') + 1
        elif event_type == 'CLICK_DETAILS': promo.clicks_count = F('clicks_count') + 1
        elif event_type == 'WHATSAPP': promo.whatsapp_clicks = F('whatsapp_clicks') + 1
        elif event_type == 'CALL': promo.call_clicks = F('call_clicks') + 1
        promo.save(update_fields=['views_count', 'clicks_count', 'whatsapp_clicks', 'call_clicks'])

    log.save()
    return Response({'status': 'tracked'})

@api_view(['GET'])
@permission_classes([IsAdminUser])
def get_dashboard_stats(request):
    top_viewed_listings = Listing.objects.order_by('-views_count')[:5]
    top_contacted_listings = Listing.objects.order_by('-whatsapp_clicks')[:5]
    top_promos = Promotion.objects.order_by('-clicks_count')[:5]
    
    return Response({
        'top_viewed_listings': ListingSerializer(top_viewed_listings, many=True).data,
        'top_contacted_listings': ListingSerializer(top_contacted_listings, many=True).data,
        'top_promos': PromotionSerializer(top_promos, many=True).data
    })

class AdminDashboardStatsView(APIView):
    permission_classes = [IsAdminUser] 

    def get(self, request):
        total_listings = Listing.objects.count()
        total_users = User.objects.count()
        total_waiver_leads = WaiverLead.objects.count()

        l_views = Listing.objects.aggregate(Sum('views_count'))['views_count__sum'] or 0
        p_views = Promotion.objects.aggregate(Sum('views_count'))['views_count__sum'] or 0
        total_views = l_views + p_views

        l_wa = Listing.objects.aggregate(Sum('whatsapp_clicks'))['whatsapp_clicks__sum'] or 0
        l_call = Listing.objects.aggregate(Sum('call_clicks'))['call_clicks__sum'] or 0
        p_wa = Promotion.objects.aggregate(Sum('whatsapp_clicks'))['whatsapp_clicks__sum'] or 0
        p_call = Promotion.objects.aggregate(Sum('call_clicks'))['call_clicks__sum'] or 0
        total_clicks = l_wa + l_call + p_wa + p_call
        
        return Response({
            "total_listings": total_listings,
            "total_users": total_users,
            "total_views": total_views,
            "total_clicks": total_clicks,
            'total_waiver_leads': total_waiver_leads,
        })

class SmartTrackEventView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        event_type = request.data.get('event_type')
        listing_id = request.data.get('listing_id')
        promotion_id = request.data.get('promo_id')
        
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        ip = x_forwarded_for.split(',')[0] if x_forwarded_for else request.META.get('REMOTE_ADDR')
        
        user = request.user if request.user.is_authenticated else None

        time_threshold = now() - timedelta(minutes=10)
        exists = AnalyticsLog.objects.filter(
            ip_address=ip, event_type=event_type, created_at__gte=time_threshold
        )
        if listing_id: exists = exists.filter(listing_id=listing_id)
        if promotion_id: exists = exists.filter(promotion_id=promotion_id)
        
        if exists.exists():
            return Response({"status": "ignored", "msg": "Duplicate event prevented"})

        AnalyticsLog.objects.create(
            event_type=event_type, listing_id=listing_id, 
            promotion_id=promotion_id, user=user, ip_address=ip
        )

        if listing_id:
            listing = Listing.objects.get(id=listing_id)
            if event_type == 'VIEW_LISTING': listing.views_count += 1
            elif event_type == 'CLICK_WHATSAPP': listing.whatsapp_clicks += 1
            elif event_type == 'CLICK_CALL': listing.call_clicks += 1
            listing.save(update_fields=['views_count', 'whatsapp_clicks', 'call_clicks'])

        if promotion_id:
            promo = Promotion.objects.get(id=promotion_id)
            if event_type == 'VIEW_PROMO': promo.views_count += 1
            elif event_type == 'CLICK_WHATSAPP': promo.whatsapp_clicks += 1
            elif event_type == 'CLICK_CALL': promo.call_clicks += 1
            promo.save(update_fields=['views_count', 'whatsapp_clicks', 'call_clicks'])

        return Response({"status": "success"})

class AdminListingsView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        listings = Listing.objects.select_related('agent').order_by('-created_at')
        
        data = []
        for l in listings:
            data.append({
                "id": l.id,
                "title": l.title,
                "price": l.price,
                "status": l.status,
                "offer_type": l.get_offer_type_display(),
                "agent_name": f"{l.agent.first_name} {l.agent.last_name}".strip() if l.agent and l.agent.first_name else (l.agent.username if l.agent else "المدير"),
                "created_at": l.created_at.strftime("%Y-%m-%d"),
                "views": l.views_count
            })
        return Response(data)

class AdminUpdateListingStatusView(APIView):
    permission_classes = [IsAdminUser]

    def post(self, request, pk):
        try:
            listing = Listing.objects.get(pk=pk)
            new_status = request.data.get('status') 
            
            if new_status in dict(Listing.STATUS_CHOICES).keys():
                listing.status = new_status
                listing.save(update_fields=['status'])
                
                if new_status == 'Available' and listing.agent:
                    Notification.objects.get_or_create(
                        user=listing.agent, 
                        title="مبروك! 🥳", 
                        message=f"تم نشر إعلانك '{listing.title}' بنجاح.", 
                        notification_type='Listing'
                    )
                    send_push_notification(
                        listing.agent, 
                        "تم نشر إعلانك! 🏠", 
                        f"وافق الإدارة على عقارك: {listing.title}.", 
                        link=f"/listings/{listing.id}"
                    )

                return Response({'status': 'success', 'new_status': new_status})
            return Response({'error': 'حالة غير صالحة'}, status=400)
        except Listing.DoesNotExist:
            return Response({'error': 'العقار غير موجود'}, status=404)
        
class AdminPromotionsView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        promos = Promotion.objects.all().order_by('display_order', '-created_at')
        data = []
        for p in promos:
            data.append({
                "id": p.id,
                "title": p.title,
                "type": p.get_promo_type_display(),
                "is_active": p.is_active,
                "views": p.views_count,
                "clicks": p.clicks_count,
                "order": p.display_order
            })
        return Response(data)

class AdminTogglePromotionView(APIView):
    permission_classes = [IsAdminUser]

    def post(self, request, pk):
        try:
            promo = Promotion.objects.get(pk=pk)
            promo.is_active = not promo.is_active  
            promo.save(update_fields=['is_active'])
            return Response({'status': 'success', 'is_active': promo.is_active})
        except Promotion.DoesNotExist:
            return Response({'error': 'الإعلان غير موجود'}, status=404)

class AdminCreatePromotionView(APIView):
    permission_classes = [IsAdminUser]

    @transaction.atomic 
    def post(self, request):
        data = request.data
        try:
            target_listing_id = data.get('target_listing_id')
            target_listing = Listing.objects.filter(id=target_listing_id).first() if target_listing_id else None

            promo = Promotion.objects.create(
                title=data.get('title'),
                subtitle=data.get('subtitle', ''),
                promo_type=data.get('promo_type', 'GENERAL'),
                cover_image=data.get('cover_image'), 
                developer_logo=data.get('developer_logo', ''),
                master_plan=data.get('master_plan', ''),
                youtube_url=data.get('youtube_url', ''),
                target_listing=target_listing,
                description=data.get('description', ''),
                developer_name=data.get('developer_name', ''),
                payment_system=data.get('payment_system', ''),
                delivery_date=data.get('delivery_date', ''),
                project_features=data.get('project_features', ''),
                price_start_from=data.get('price_start_from') or None,
                phone_number=data.get('phone_number', ''),
                whatsapp_number=data.get('whatsapp_number', ''),
                is_active=data.get('is_active', True),
                display_order=data.get('display_order', 0),
                latitude=data.get('latitude') or None,
                longitude=data.get('longitude') or None,
                address=data.get('address', ''), 
            )

            gallery = data.get('gallery', [])
            for img_url in gallery:
                PromotionImage.objects.create(promotion=promo, image=img_url)

            transformations = data.get('transformations', [])
            for t in transformations:
                Transformation.objects.create(
                    promotion=promo,
                    before_image=t.get('before'),
                    after_image=t.get('after'),
                    title=t.get('title', '')
                )

            units = data.get('units', [])
            for u in units:
                PromotionUnit.objects.create(
                    promotion=promo,
                    custom_title=u.get('custom_title', ''),
                    price=u.get('price') or None,   
                    image=u.get('image', '')        
                )

            return Response({'status': 'success', 'id': promo.id})
        except Exception as e:
            return Response({'error': str(e)}, status=400)

class AdminGeographyView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        govs = Governorate.objects.prefetch_related(
            'city_set__majorzone_set__subdivision_set'
        ).all()

        data = []
        for g in govs:
            gov_data = {"id": g.id, "name": g.name, "cities": []}
            for c in g.city_set.all():
                city_data = {"id": c.id, "name": c.name, "zones": []}
                for z in c.majorzone_set.all():
                    zone_data = {"id": z.id, "name": z.name, "subdivisions": []}
                    for s in z.subdivision_set.all():
                        zone_data["subdivisions"].append({"id": s.id, "name": s.name})
                    city_data["zones"].append(zone_data)
                gov_data["cities"].append(city_data)
            data.append(gov_data)
            
        return Response(data)

    def post(self, request):
        level = request.data.get('level')
        name = request.data.get('name')
        parent_id = request.data.get('parent_id')

        try:
            if level == 'gov':
                Governorate.objects.create(name=name)
            elif level == 'city':
                City.objects.create(name=name, governorate_id=parent_id)
            elif level == 'zone':
                MajorZone.objects.create(name=name, city_id=parent_id)
            elif level == 'subdivision':
                Subdivision.objects.create(name=name, major_zone_id=parent_id)
            else:
                return Response({'error': 'مستوى غير معروف'}, status=400)
                
            return Response({'status': 'success'})
        except Exception as e:
            return Response({'error': str(e)}, status=400)

class AdminDeleteGeographyView(APIView):
    permission_classes = [IsAdminUser]

    def post(self, request):
        level = request.data.get('level')
        item_id = request.data.get('id')
        action = request.data.get('action') 

        try:
            if level == 'gov':
                obj = Governorate.objects.get(id=item_id)
                count = Listing.objects.filter(governorate=obj).count()
            elif level == 'city':
                obj = City.objects.get(id=item_id)
                count = Listing.objects.filter(city=obj).count()
            elif level == 'zone':
                obj = MajorZone.objects.get(id=item_id)
                count = Listing.objects.filter(major_zone=obj).count()
            elif level == 'subdivision':
                obj = Subdivision.objects.get(id=item_id)
                count = Listing.objects.filter(subdivision=obj).count()
            else:
                return Response({'error': 'مستوى غير صالح'}, status=400)

            if action == 'check':
                return Response({'count': count})
            
            elif action == 'delete':
                obj.delete() 
                return Response({'status': 'success'})

        except Exception as e:
            return Response({'error': str(e)}, status=400)


class WaiverSearchView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        data = request.data
        plot = str(data.get('plot', '')).strip()
        neighborhood = str(data.get('neighborhood', '')).strip()
        district = str(data.get('district', '')).strip()
        full_name = data.get('full_name')
        phone_number = data.get('phone_number')

        if not all([plot, neighborhood, district, full_name, phone_number]):
            return Response({'error': 'جميع الحقول مطلوبة'}, status=400)

        waiver = Waiver.objects.filter(
            plot_number=plot, neighborhood=neighborhood, district=district
        ).first()

        status_val = 'Success' if waiver else 'Pending'

        WaiverLead.objects.create(
            phone_number=phone_number,
            full_name=full_name,
            plot_number=plot,
            neighborhood=neighborhood,
            district=district,
            status=status_val
        )

        if waiver:
            return Response({
                'status': 'success',
                'data': {
                    'plot': waiver.plot_number,
                    'neighborhood': waiver.neighborhood,
                    'district': waiver.district,
                    'procedure': waiver.procedure,
                    'committee_number': waiver.committee_number,
                    'date': waiver.procedure_date, 
                }
            })
        else:
            return Response({'status': 'pending'})


class AdminUploadWaiversView(APIView):
    permission_classes = [IsAdminUser]
    parser_classes = [MultiPartParser]

    def post(self, request):
        file = request.FILES.get('file')
        if not file: return Response({'error': 'لم يتم رفع أي ملف'}, status=400)
        if file.size > 5 * 1024 * 1024:
            return Response({'error': 'حجم الملف كبير جداً! الحد الأقصى 5 ميجابايت.'}, status=400)
        try:
            if file.name.endswith('.csv'):
                df = pd.read_csv(file)
            else:
                df = pd.read_excel(file)
                
            expected_columns = ['لجنة', 'تاريخ', 'الاجراء', 'ق', 'مج', 'حى']
            for col in expected_columns:
                if col not in df.columns:
                    return Response({'error': f'العمود "{col}" غير موجود في الملف'}, status=400)

            count = 0
            for index, row in df.iterrows():
                raw_date = str(row['تاريخ']).strip()
                if ' ' in raw_date:
                    raw_date = raw_date.split(' ')[0]

                Waiver.objects.update_or_create(
                    district=str(row['حى']).strip(),
                    neighborhood=str(row['مج']).strip(),
                    plot_number=str(row['ق']).strip(),
                    defaults={
                        'procedure': str(row['الاجراء']).strip(),
                        'committee_number': str(row['لجنة']).strip(),
                        'procedure_date': raw_date, 
                    }
                )
                count += 1
            return Response({'status': 'success', 'message': f'تم رفع {count} تنازل بنجاح! 🎉'})
        except Exception as e:
            return Response({'error': f'حدث خطأ في قراءة الملف: {str(e)}'}, status=400)

class AdminExportWaiverLeadsView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        leads = WaiverLead.objects.all().values(
            'phone_number', 'full_name', 'plot_number', 'neighborhood', 'district', 'status'
        )
        
        df = pd.DataFrame(leads)
        if df.empty:
            return Response({'error': 'لا يوجد بيانات لتصديرها حالياً'}, status=400)
        
        df.rename(columns={
            'phone_number': 'رقم الفون',
            'full_name': 'الاسم',
            'plot_number': 'رقم القطعة',
            'neighborhood': 'المجاورة',
            'district': 'الحي',
            'status': 'حالة التنازل'
        }, inplace=True)
        
        df['حالة التنازل'] = df['حالة التنازل'].map({'Success': 'تم التنازل', 'Pending': 'قيد الانتظار'})

        response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        response['Content-Disposition'] = 'attachment; filename="waiver_clients_data.xlsx"'
        df.to_excel(response, index=False, engine='openpyxl')
        
        return response

class AdminWaiverLeadsListView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        leads = WaiverLead.objects.all().order_by('-created_at')
        data = []
        for lead in leads:
            data.append({
                "id": lead.id,
                "full_name": lead.full_name,
                "phone_number": lead.phone_number,
                "plot": lead.plot_number,
                "neighborhood": lead.neighborhood,
                "district": lead.district,
                "status": lead.status,
                "created_at": lead.created_at.strftime("%Y-%m-%d %H:%M")
            })
        return Response(data)

class AdminDeleteWaiverLeadView(APIView):
    permission_classes = [IsAdminUser]

    def delete(self, request, pk):
        try:
            lead = WaiverLead.objects.get(pk=pk)
            lead.delete()
            return Response({"status": "success", "message": "تم حذف العميل بنجاح"})
        except WaiverLead.DoesNotExist:
            return Response({"error": "العميل غير موجود"}, status=404)

class AdminDeleteAllWaiversView(APIView):
    permission_classes = [IsAdminUser]

    def delete(self, request):
        try:
            count, _ = Waiver.objects.all().delete()
            return Response({"status": "success", "message": f"تم مسح {count} سجل تنازل بنجاح!"})
        except Exception as e:
            return Response({"error": "حدث خطأ أثناء مسح البيانات"}, status=500)


# ==========================================
# 🚀 API لتوليد توقيع آمن لرفع الصور لكلاوديناري
# ==========================================
class CloudinarySignatureView(APIView):
    # لا يمكن لأي شخص طلب التوقيع إلا لو كان مسجل دخول
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        folder = request.data.get('folder', 'rawasi_uploads')
        timestamp = int(time.time())

        # المعاملات التي سيتم توقيعها (يجب أن تتطابق مع الفرونت-إند)
        params_to_sign = {
            'folder': folder,
            'timestamp': timestamp
        }

        # جلب الـ API Secret من إعدادات Django
        api_secret = settings.CLOUDINARY_STORAGE.get('API_SECRET') or os.environ.get('CLOUDINARY_API_SECRET')
        
        signature = cloudinary.utils.api_sign_request(
            params_to_sign,
            api_secret
        )

        return Response({
            'signature': signature,
            'timestamp': timestamp,
            'cloud_name': settings.CLOUDINARY_STORAGE.get('CLOUD_NAME') or os.environ.get('CLOUDINARY_CLOUD_NAME'),
            'api_key': settings.CLOUDINARY_STORAGE.get('API_KEY') or os.environ.get('CLOUDINARY_API_KEY'),
        })