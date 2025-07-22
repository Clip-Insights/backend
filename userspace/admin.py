from django.contrib import admin
from .models import File, Folder

# Register File model
@admin.register(File)
class FileAdmin(admin.ModelAdmin):
    list_display = ('id', 'user_id', 'short_path', 'short_name', 'created_date', 'folder_id', 'size')  # All fields, with truncated path and name
    search_fields = ('path', 'name')  # Searchable text fields
    list_filter = ('created_date', 'size')  # Filters for date and numeric fields
    readonly_fields = ('id', 'user_id', 'created_date', 'folder_id')  # Non-editable fields
    fieldsets = (
        (None, {
            'fields': ('id', 'user_id', 'path', 'name', 'created_date', 'folder_id', 'size')
        }),
    )

    def short_path(self, obj):
        """Display the first 100 characters of the file path."""
        return obj.path[:100] + '...' if obj.path and len(obj.path) > 100 else obj.path or ''
    short_path.short_description = 'Path'  # Label for admin column

    def short_name(self, obj):
        """Display the first 100 characters of the file name."""
        return obj.name[:100] + '...' if obj.name and len(obj.name) > 100 else obj.name or ''
    short_name.short_description = 'Name'  # Label for admin column

# Register Folder model
@admin.register(Folder)
class FolderAdmin(admin.ModelAdmin):
    list_display = ('id', 'short_name', 'user_id', 'created_date')  # All fields, with truncated name
    search_fields = ('name',)  # Searchable text fields
    list_filter = ('created_date',)  # Filters for date fields
    readonly_fields = ('id', 'created_date')  # Non-editable fields
    fieldsets = (
        (None, {
            'fields': ('id', 'name', 'user_id', 'created_date')
        }),
    )

    def short_name(self, obj):
        """Display the first 100 characters of the folder name."""
        return obj.name[:100] + '...' if obj.name and len(obj.name) > 100 else obj.name or ''
    short_name.short_description = 'Name'  # Label for admin column