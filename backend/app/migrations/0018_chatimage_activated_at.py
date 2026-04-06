from django.db import migrations, models
from django.utils import timezone


def backfill_active_image_order(apps, schema_editor):
    ChatImage = apps.get_model("app", "ChatImage")
    for image in ChatImage.objects.filter(is_active=True, activated_at__isnull=True):
        image.activated_at = image.uploaded_at or timezone.now()
        image.save(update_fields=["activated_at"])


class Migration(migrations.Migration):

    dependencies = [
        ("app", "0017_chatconversations_image_attachments_snapshot"),
    ]

    operations = [
        migrations.AddField(
            model_name="chatimage",
            name="activated_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.RunPython(backfill_active_image_order, migrations.RunPython.noop),
    ]
