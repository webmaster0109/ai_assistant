from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("app", "0013_backgroundjob_chatdocument_processing"),
    ]

    operations = [
        migrations.AddField(
            model_name="learningquizsession",
            name="difficulty_level",
            field=models.CharField(
                choices=[
                    ("beginner", "Beginner"),
                    ("intermediate", "Intermediate"),
                    ("advanced", "Advanced"),
                    ("master", "Master"),
                    ("enterprises mastery", "Enterprises mastery"),
                ],
                default="beginner",
                max_length=40,
            ),
        ),
    ]
