import django_filters
from .models import Listing

class ListingFilter(django_filters.FilterSet):
    # ✅ ترجمة أسماء الفرونت إند لاستعلامات دجانجو
    min_price = django_filters.NumberFilter(field_name="price", lookup_expr='gte')
    max_price = django_filters.NumberFilter(field_name="price", lookup_expr='lte')
    
    min_area = django_filters.NumberFilter(field_name="area_sqm", lookup_expr='gte')
    max_area = django_filters.NumberFilter(field_name="area_sqm", lookup_expr='lte')

    # فلاتر الموقع (Exact Match)
    governorate = django_filters.NumberFilter(field_name="governorate")
    city = django_filters.NumberFilter(field_name="city")
    major_zone = django_filters.NumberFilter(field_name="major_zone")
    subdivision = django_filters.NumberFilter(field_name="subdivision")

    # فلاتر أخرى
    offer_type = django_filters.CharFilter(field_name="offer_type")
    category = django_filters.NumberFilter(field_name="category")
    status = django_filters.CharFilter(field_name="status")
    is_finance_eligible = django_filters.BooleanFilter(field_name="is_finance_eligible")

    # ⚠️ ملحوظة: شلنا bedrooms, bathrooms من هنا لأننا هنعتمد على الـ Dynamic Features في الـ View

    class Meta:
        model = Listing
        fields = ['offer_type', 'category', 'status', 'is_finance_eligible']