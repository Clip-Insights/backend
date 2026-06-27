from django.db import models
from datetime import datetime
from django.utils.timezone import now
import uuid

class File(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user_id = models.UUIDField(default=uuid.uuid4, editable=False)
    path = models.CharField(max_length=255)
    name = models.CharField(max_length=255, default="filename") 
    created_date = models.DateTimeField(default=now)
    folder_id = models.UUIDField(default=0, editable=False)
    size = models.FloatField(default=0, verbose_name="Size in bytes", help_text="Size of the file in bytes")

    def __str__(self):
        return f"User {self.user_id} - {self.file_path} - {self.file_name}"
    

class Folder(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    user_id = models.UUIDField(null=False)
    created_date = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name}"
