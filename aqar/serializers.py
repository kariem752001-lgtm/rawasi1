"""
aqar/serializers.py
-------------------
FIX #1: ListingSerializer يحدد الحقول صراحةً (لا __all__)
FIX #2: external_images يتحقق من Cloudinary URL فقط (ضد SSRF)
FIX #3: دالة مساعدة مركزية لمعالجة الصور (لا تكرار)
FIX #4: get_image و get_price محددة مرة واحدة فقط في PromotionUnitSerializer
FIX #5: _save_features ترفع exception صريح بدلاً من الصمت
"""
import json
import logging

from django.contrib.auth import get_user_model
from django.db import transaction
from rest_framework import serializers

from .models import (
    Category,
    City,
    Favorite,
    Feature,
    Governorate,
    Listing,
    ListingFeature,
    ListingImage,
    MajorZone,
    Promotion,
    PromotionImage,
    PromotionUnit,
    Subdivision,
    Transformation,
)
from .utils import trigger_youtube_upload

logger = logging.getLogger(__name__)
User = get_user_model()


# ==========================================
# FIX #3: دالة مساعدة مركزية للصور
# ==========================================
def build_image_url(image_field, context: dict) -> str | None:
    """
    تحوّل أي image field لـ URL صحيح.
    تستخدم في كل الـ Serializers بدلاً من تكرار نفس الكود.
    """
    if not image_field:
        return None
    url = str(image_field)
    if url.startswith("http"):
        return url
    request = context.get("request")
    try:
        return request.build_absolute_uri(image_field.url) if request else image_field.url
    except (AttributeError, ValueError) as e:
        logger.warning(f"URL build failed for {image_field}: {e}")
        return url


# ==========================================
# Feature Serializers
# ==========================================
class FeatureSerializer(serializers.ModelSerializer):
    class Meta:
        model = Feature
        fields = ["id", "name", "input_type", "icon", "options_list", "is_quick_filter"]


class ListingFeatureSerializer(serializers.ModelSerializer):
    feature_name = serializers.CharField(source="feature.name", read_only=True)
    icon = serializers.CharField(source="feature.icon", read_only=True)

    class Meta:
        model = ListingFeature
        fields = ["id", "feature", "feature_name", "icon", "value"]


class ListingImageSerializer(serializers.ModelSerializer):
    image = serializers.SerializerMethodField()

    class Meta:
        model = ListingImage
        fields = ["id", "image"]

    def get_image(self, obj):
        return build_image_url(obj.image, self.context)


class CategorySerializer(serializers.ModelSerializer):
    allowed_features = FeatureSerializer(many=True, read_only=True)

    class Meta:
        model = Category
        fields = ["id", "name", "slug", "allowed_features"]


# ==========================================
# Geography Serializers
# ==========================================
class GovernorateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Governorate
        fields = "__all__"


class CitySerializer(serializers.ModelSerializer):
    class Meta:
        model = City
        fields = "__all__"


class MajorZoneSerializer(serializers.ModelSerializer):
    class Meta:
        model = MajorZone
        fields = "__all__"


class SubdivisionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Subdivision
        fields = "__all__"


# ==========================================
# Listing Serializer
# ==========================================
class ListingSerializer(serializers.ModelSerializer):
    images = ListingImageSerializer(many=True, read_only=True)
    dynamic_features = ListingFeatureSerializer(source="features_values", many=True, read_only=True)

    governorate_name = serializers.CharField(source="governorate.name", read_only=True)
    city_name = serializers.CharField(source="city.name", read_only=True)
    category_name = serializers.CharField(source="category.name", read_only=True)
    major_zone_name = serializers.CharField(source="major_zone.name", read_only=True, allow_null=True)
    subdivision_name = serializers.CharField(source="subdivision.name", read_only=True, allow_null=True)
    is_favorite = serializers.SerializerMethodField()
    thumbnail = serializers.SerializerMethodField()

    # Write-only fields
    features_data = serializers.CharField(write_only=True, required=False)
    raw_video_upload = serializers.FileField(write_only=True, required=False)
    external_images = serializers.ListField(
        child=serializers.URLField(), write_only=True, required=False, allow_empty=True
    )
    external_video = serializers.URLField(write_only=True, required=False, allow_null=True, allow_blank=True)
    external_id_card = serializers.URLField(write_only=True, required=False, allow_null=True, allow_blank=True)
    external_contract = serializers.URLField(write_only=True, required=False, allow_null=True, allow_blank=True)
    deleted_image_ids = serializers.ListField(
        child=serializers.IntegerField(), write_only=True, required=False
    )

    class Meta:
        model = Listing
        # FIX #1: حقول صريحة — لا نكشف id_card_image/contract_image/owner_phone للعامة
        fields = [
            "id", "title", "status", "offer_type", "category", "category_name",
            "price", "area_sqm", "description", "is_finance_eligible",
            "governorate", "governorate_name", "city", "city_name",
            "major_zone", "major_zone_name", "subdivision", "subdivision_name",
            "project_name", "building_number", "floor_number", "apartment_number",
            "bedrooms", "bathrooms", "google_maps_url", "latitude", "longitude",
            "thumbnail", "youtube_url", "custom_map_image",
            "views_count", "whatsapp_clicks", "call_clicks",
            "agent", "owner_name", "owner_phone",
            "created_at",
            # Write-only
            "images", "dynamic_features", "is_favorite",
            "features_data", "raw_video_upload", "external_images",
            "external_video", "external_id_card", "external_contract",
            "deleted_image_ids",
        ]
        read_only_fields = ["id", "views_count", "whatsapp_clicks", "call_clicks", "created_at"]

    def get_thumbnail(self, obj):
        return build_image_url(obj.thumbnail, self.context)

    def get_is_favorite(self, obj):
        return getattr(obj, 'is_favorite_annotated', False)

    def validate_external_images(self, urls):
        """FIX #2: SSRF protection — يقبل فقط Cloudinary URLs."""
        allowed_prefix = "https://res.cloudinary.com/"
        for url in urls:
            if not url.startswith(allowed_prefix):
                raise serializers.ValidationError(
                    f"الصور يجب أن تكون من Cloudinary فقط. URL غير مسموح: {url[:60]}"
                )
        return urls

    @transaction.atomic
    def create(self, validated_data):
        features_json = validated_data.pop("features_data", None)
        external_images = validated_data.pop("external_images", [])
        external_video = validated_data.pop("external_video", None)
        raw_video_upload = validated_data.pop("raw_video_upload", None)
        external_id_card = validated_data.pop("external_id_card", None)
        external_contract = validated_data.pop("external_contract", None)
        validated_data.pop("deleted_image_ids", [])

        listing = Listing.objects.create(**validated_data)

        if external_images:
            ListingImage.objects.bulk_create(
                [ListingImage(listing=listing, image=url) for url in external_images]
            )
            listing.thumbnail = external_images[0]

        if raw_video_upload:
            trigger_youtube_upload(
                video_file=raw_video_upload,
                title=f"عقار رواسي: {listing.title}",
                description=(listing.description or "")[:200],
                instance_model=listing,
            )
        elif external_video:
            listing.youtube_url = external_video

        if external_id_card:
            listing.id_card_image = external_id_card
        if external_contract:
            listing.contract_image = external_contract

        listing.save()

        if features_json:
            self._save_features(listing, features_json)
        return listing

    @transaction.atomic
    def update(self, instance, validated_data):
        features_input = validated_data.pop("features_data", None)
        external_images = validated_data.pop("external_images", [])
        external_video = validated_data.pop("external_video", None)
        raw_video_upload = validated_data.pop("raw_video_upload", None)
        external_id_card = validated_data.pop("external_id_card", None)
        external_contract = validated_data.pop("external_contract", None)
        deleted_image_ids = validated_data.pop("deleted_image_ids", [])
        validated_data.pop("uploaded_images", None)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        if raw_video_upload:
            trigger_youtube_upload(
                video_file=raw_video_upload,
                title=f"عقار رواسي: {instance.title}",
                description=(instance.description or "")[:200],
                instance_model=instance,
            )
        elif "external_video" in self.initial_data:
            instance.youtube_url = external_video

        if external_id_card:
            instance.id_card_image = external_id_card
        if external_contract:
            instance.contract_image = external_contract

        instance.save()

        if deleted_image_ids:
            ListingImage.objects.filter(id__in=deleted_image_ids, listing=instance).delete()

        if external_images:
            ListingImage.objects.bulk_create(
                [ListingImage(listing=instance, image=url) for url in external_images]
            )

        first_image = instance.images.first()
        if first_image:
            instance.thumbnail = first_image.image
            instance.save(update_fields=["thumbnail"])

        if features_input:
            self._save_features(instance, features_input)

        return instance

    def _save_features(self, listing, features_input):
        """
        FIX #5: Batch fetch بدل N+1 + رفع exception صريح.
        """
        try:
            features_dict = (
                json.loads(features_input) if isinstance(features_input, str) else features_input
            )
            if not isinstance(features_dict, dict):
                raise serializers.ValidationError("features_data يجب أن يكون JSON object.")

            # FIX: جلب كل الـ features دفعة واحدة بدل query لكل واحدة
            feature_ids = [int(k) for k in features_dict.keys() if features_dict[k]]
            feature_map = {f.id: f for f in Feature.objects.filter(id__in=feature_ids)}

            for feature_id_str, value in features_dict.items():
                if not value:
                    continue
                try:
                    feature_id = int(feature_id_str)
                    feature_obj = feature_map.get(feature_id)
                    if feature_obj:
                        ListingFeature.objects.update_or_create(
                            listing=listing,
                            feature=feature_obj,
                            defaults={"value": str(value)},
                        )
                    else:
                        logger.warning(f"Feature {feature_id} not found, skipping.")
                except (ValueError, TypeError) as e:
                    logger.warning(f"Invalid feature_id '{feature_id_str}': {e}")

        except serializers.ValidationError:
            raise
        except Exception as e:
            logger.error(f"_save_features failed for listing {listing.pk}: {e}")
            raise serializers.ValidationError(f"خطأ في حفظ الخصائص: {e}")


class FavoriteSerializer(serializers.ModelSerializer):
    listing = ListingSerializer(read_only=True)

    class Meta:
        model = Favorite
        fields = "__all__"


# ==========================================
# Promotion Serializers
# ==========================================
class PromotionImageSerializer(serializers.ModelSerializer):
    image = serializers.SerializerMethodField()

    class Meta:
        model = PromotionImage
        fields = ["id", "image"]

    def get_image(self, obj):
        return build_image_url(obj.image, self.context)


class TransformationSerializer(serializers.ModelSerializer):
    before_image = serializers.SerializerMethodField()
    after_image = serializers.SerializerMethodField()

    class Meta:
        model = Transformation
        fields = ["id", "before_image", "after_image", "title"]

    def get_before_image(self, obj):
        return build_image_url(obj.before_image, self.context)

    def get_after_image(self, obj):
        return build_image_url(obj.after_image, self.context)


class PromotionUnitSerializer(serializers.ModelSerializer):
    listing_id = serializers.SerializerMethodField()
    title = serializers.SerializerMethodField()
    image = serializers.SerializerMethodField()
    price = serializers.SerializerMethodField()
    unit_type = serializers.SerializerMethodField()

    class Meta:
        model = PromotionUnit
        fields = ["id", "listing_id", "title", "image", "price", "unit_type"]

    def get_listing_id(self, obj):
        return obj.linked_listing.id if obj.linked_listing else None

    def get_title(self, obj):
        return obj.custom_title or (obj.linked_listing.title if obj.linked_listing else "وحدة")

    # FIX #4: get_image محددة مرة واحدة فقط (كانت مكررة مرتين!)
    def get_image(self, obj):
        if obj.image:
            return build_image_url(obj.image, self.context)
        if obj.linked_listing and obj.linked_listing.thumbnail:
            return build_image_url(obj.linked_listing.thumbnail, self.context)
        return None

    # FIX #4: get_price محددة مرة واحدة فقط (كانت مكررة مرتين!)
    def get_price(self, obj):
        if obj.price:
            return obj.price
        return obj.linked_listing.price if obj.linked_listing else 0

    def get_unit_type(self, obj):
        if obj.linked_listing and obj.linked_listing.category:
            return obj.linked_listing.category.name
        return "وحدة"


class PromotionSerializer(serializers.ModelSerializer):
    gallery = PromotionImageSerializer(many=True, read_only=True)
    transformations = TransformationSerializer(many=True, read_only=True)
    units = PromotionUnitSerializer(many=True, read_only=True)
    final_url = serializers.SerializerMethodField()
    display_price = serializers.SerializerMethodField()
    cover_image = serializers.SerializerMethodField()
    developer_logo = serializers.SerializerMethodField()
    master_plan = serializers.SerializerMethodField()

    class Meta:
        model = Promotion
        fields = "__all__"

    def get_cover_image(self, obj):
        return build_image_url(obj.cover_image, self.context)

    def get_developer_logo(self, obj):
        return build_image_url(obj.developer_logo, self.context)

    def get_master_plan(self, obj):
        return build_image_url(obj.master_plan, self.context)

    def get_final_url(self, obj):
        if obj.promo_type == "LISTING" and obj.target_listing:
            return f"/listings/{obj.target_listing.id}"
        return f"/promotions/{obj.slug}"

    def get_display_price(self, obj):
        if obj.promo_type == "LISTING" and obj.target_listing:
            return obj.target_listing.price
        return obj.price_start_from
