from rest_framework import serializers

from .models import ServiceCategory


class SubcategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = ServiceCategory
        fields = ["id", "slug", "name_en", "name_sw", "icon"]


class CategorySerializer(serializers.ModelSerializer):
    children = serializers.SerializerMethodField()

    class Meta:
        model = ServiceCategory
        fields = ["id", "slug", "name_en", "name_sw", "icon", "children"]

    def get_children(self, obj):
        children = [c for c in obj.children.all() if c.is_active]
        return SubcategorySerializer(children, many=True).data
