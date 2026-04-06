from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("app", "0011_learningquizsession_learningquizquestion_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="ChatImage",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("file", models.FileField(upload_to="chat_images/")),
                ("filename", models.CharField(max_length=255)),
                ("file_hash", models.CharField(blank=True, default="", max_length=64)),
                ("content_type", models.CharField(blank=True, default="", max_length=100)),
                ("is_active", models.BooleanField(default=False)),
                ("uploaded_at", models.DateTimeField(auto_now_add=True)),
                (
                    "session",
                    models.ForeignKey(on_delete=models.deletion.CASCADE, related_name="images", to="app.chatsession"),
                ),
            ],
            options={
                "indexes": [
                    models.Index(fields=["session", "-is_active", "-uploaded_at"], name="app_chatimg_sess_a_idx"),
                    models.Index(fields=["session", "file_hash"], name="app_chatimg_sess_f_idx"),
                ],
            },
        ),
        migrations.AddField(
            model_name="chatconversations",
            name="image_attachment",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=models.deletion.SET_NULL,
                related_name="conversations",
                to="app.chatimage",
            ),
        ),
    ]
