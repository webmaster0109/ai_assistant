from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("app", "0009_chatdocument_is_active_and_multiple_docs"),
    ]

    operations = [
        migrations.AddField(
            model_name="chatdocument",
            name="file_hash",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.AddIndex(
            model_name="chatdocument",
            index=models.Index(fields=["session", "file_hash"], name="app_chatdoc_sess_f_idx"),
        ),
    ]
