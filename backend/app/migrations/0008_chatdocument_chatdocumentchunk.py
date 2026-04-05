from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("app", "0007_chatsession_public_share"),
    ]

    operations = [
        migrations.CreateModel(
            name="ChatDocument",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("file", models.FileField(upload_to="chat_documents/")),
                ("filename", models.CharField(max_length=255)),
                ("uploaded_at", models.DateTimeField(auto_now_add=True)),
                ("extracted_characters", models.IntegerField(default=0)),
                (
                    "session",
                    models.OneToOneField(on_delete=models.deletion.CASCADE, related_name="document", to="app.chatsession"),
                ),
            ],
        ),
        migrations.CreateModel(
            name="ChatDocumentChunk",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("chunk_index", models.PositiveIntegerField()),
                ("page_number", models.PositiveIntegerField(blank=True, null=True)),
                ("content", models.TextField()),
                (
                    "document",
                    models.ForeignKey(on_delete=models.deletion.CASCADE, related_name="chunks", to="app.chatdocument"),
                ),
            ],
            options={
                "ordering": ["chunk_index"],
                "indexes": [models.Index(fields=["document", "chunk_index"], name="app_doc_chunk_idx")],
            },
        ),
    ]
