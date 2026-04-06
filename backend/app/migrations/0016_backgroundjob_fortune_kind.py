from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("app", "0015_backgroundjob_roast_kind"),
    ]

    operations = [
        migrations.AlterField(
            model_name="backgroundjob",
            name="kind",
            field=models.CharField(
                choices=[
                    ("learning_quiz", "Learning quiz"),
                    ("learning_path", "Learning path"),
                    ("document_ingest", "Document ingest"),
                    ("roast", "Roast"),
                    ("fortune", "Fortune"),
                ],
                max_length=50,
            ),
        ),
    ]
