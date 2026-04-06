from django.conf import settings
from django.db import migrations, models

import app.models


def mark_existing_documents_ready(apps, schema_editor):
    ChatDocument = apps.get_model("app", "ChatDocument")
    ChatDocument.objects.exclude(extracted_characters=0).update(processing_status="ready")


class Migration(migrations.Migration):

    dependencies = [
        ("app", "0012_chatimage_chatconversations_image_attachment"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="chatdocument",
            name="processing_error",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="chatdocument",
            name="processing_status",
            field=models.CharField(
                choices=[
                    ("queued", "Queued"),
                    ("processing", "Processing"),
                    ("ready", "Ready"),
                    ("failed", "Failed"),
                ],
                default="queued",
                max_length=20,
            ),
        ),
        migrations.RunPython(mark_existing_documents_ready, migrations.RunPython.noop),
        migrations.CreateModel(
            name="BackgroundJob",
            fields=[
                ("id", models.CharField(default=app.models.generate_uuid, editable=False, primary_key=True, serialize=False)),
                ("kind", models.CharField(choices=[("learning_quiz", "Learning quiz"), ("learning_path", "Learning path"), ("document_ingest", "Document ingest")], max_length=50)),
                ("status", models.CharField(choices=[("queued", "Queued"), ("running", "Running"), ("completed", "Completed"), ("failed", "Failed")], default="queued", max_length=20)),
                ("title", models.CharField(blank=True, default="", max_length=255)),
                ("payload", models.JSONField(blank=True, default=dict)),
                ("result", models.JSONField(blank=True, default=dict)),
                ("error_message", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                ("document", models.ForeignKey(blank=True, null=True, on_delete=models.SET_NULL, related_name="background_jobs", to="app.chatdocument")),
                ("owner", models.ForeignKey(on_delete=models.CASCADE, related_name="background_jobs", to=settings.AUTH_USER_MODEL)),
                ("session", models.ForeignKey(blank=True, null=True, on_delete=models.SET_NULL, related_name="background_jobs", to="app.chatsession")),
            ],
        ),
        migrations.AddIndex(
            model_name="backgroundjob",
            index=models.Index(fields=["owner", "status", "-created_at"], name="app_bgjob_owner_s_idx"),
        ),
        migrations.AddIndex(
            model_name="backgroundjob",
            index=models.Index(fields=["status", "created_at"], name="app_bgjob_status_c_idx"),
        ),
    ]
