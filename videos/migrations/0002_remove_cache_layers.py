from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('textutils', '0001_initial'),
    ]

    operations = [
        migrations.DeleteModel(name='VideoResource'),
        migrations.DeleteModel(name='VideoTranscriptTimeSlice'),
    ]
