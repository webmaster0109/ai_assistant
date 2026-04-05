from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("app", "0005_chatsession_owner"),
    ]

    operations = [
        migrations.AddField(
            model_name="chatsession",
            name="is_pinned",
            field=models.BooleanField(default=False),
        ),
    ]
