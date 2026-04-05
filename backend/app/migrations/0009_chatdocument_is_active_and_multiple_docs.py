from django.db import migrations, models


def mark_existing_documents_active(apps, schema_editor):
    ChatDocument = apps.get_model("app", "ChatDocument")
    ChatDocument.objects.all().update(is_active=True)


class Migration(migrations.Migration):
    dependencies = [
        ("app", "0008_chatdocument_chatdocumentchunk"),
    ]

    operations = [
        migrations.AlterField(
            model_name="chatdocument",
            name="session",
            field=models.ForeignKey(
                on_delete=models.deletion.CASCADE,
                related_name="documents",
                to="app.chatsession",
            ),
        ),
        migrations.AddField(
            model_name="chatdocument",
            name="is_active",
            field=models.BooleanField(default=False),
        ),
        migrations.AddIndex(
            model_name="chatdocument",
            index=models.Index(
                fields=["session", "-is_active", "-uploaded_at"],
                name="app_chatdoc_sess_a_idx",
            ),
        ),
        migrations.RunPython(mark_existing_documents_active, migrations.RunPython.noop),
    ]
