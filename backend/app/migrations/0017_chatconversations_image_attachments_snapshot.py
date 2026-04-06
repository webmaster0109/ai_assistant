from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("app", "0016_backgroundjob_fortune_kind"),
    ]

    operations = [
        migrations.AddField(
            model_name="chatconversations",
            name="image_attachments_snapshot",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
