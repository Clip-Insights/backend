from rest_framework import serializers
from .models import File, Folder

class FileSerializer(serializers.ModelSerializer):
    class Meta:
        model = File
        fields = [
            'id', 
            'name', 
            'path', 
            'created_date', 
            'size',
            'folder_id', 
        ]
        read_only_fields = ['id', 'created_date']  # These fields are auto-generated and should not be modified by the user

    def validate_size(self, value):
        """
        Validate that the file size is non-negative.
        """
        if value < 0:
            raise serializers.ValidationError("File size cannot be negative.")
        return value

    def validate_name(self, value):
        """
        Validate that the file name is not empty.
        """
        if not value.strip():
            raise serializers.ValidationError("File name cannot be empty.")
        return value
    

class FolderSerializer(serializers.ModelSerializer):
    items = serializers.SerializerMethodField()
    size = serializers.SerializerMethodField()
    user_id = serializers.UUIDField(write_only=True)  # Add user_id as a write-only field

    class Meta:
        model = Folder
        fields = ['id', 'name', 'items', 'size', 'user_id', 'created_date']  # Include user_id in fields

    def get_items(self, obj):
        """
        Calculate the total number of files in the folder.
        """
        return File.objects.filter(folder_id=obj.id).count()

    def get_size(self, obj):
        """
        Calculate the combined size of all files in the folder.
        """
        files = File.objects.filter(folder_id=obj.id)
        return sum(file.size for file in files)
