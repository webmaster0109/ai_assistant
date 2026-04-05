from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("app", "0006_chatsession_is_pinned"),
    ]

    operations = [
        migrations.AddField(
            model_name="chatsession",
            name="is_public",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="chatsession",
            name="share_token",
            field=models.CharField(blank=True, max_length=64, null=True, unique=True),
        ),
    ]
