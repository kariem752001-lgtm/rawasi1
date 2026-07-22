"""
aqar/permissions.py
-------------------
FIX: Staff يحتاج explicit permission عشان يعدل عقارات مش ملكه.
"""
from rest_framework import permissions


class IsOwnerOrReadOnly(permissions.BasePermission):
    """
    - القراءة: مسموحة للكل.
    - التعديل والحذف: لصاحب العقار فقط، أو staff عنده Permission صريح.
    """

    def has_object_permission(self, request, view, obj):
        # GET, HEAD, OPTIONS — مسموحة للكل
        if request.method in permissions.SAFE_METHODS:
            return True

        # صاحب العقار دايماً يقدر يعدل
        if obj.agent == request.user:
            return True

        # Staff يحتاج explicit permission — مش بس is_staff
        if request.user.is_staff and request.user.has_perm("aqar.change_listing"):
            return True

        return False
