from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("app", "0018_chatimage_activated_at"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="chatconversations",
            index=models.Index(
                fields=["session", "created_at", "id"],
                name="app_chatconv_hist_idx",
            ),
        ),
    ]
