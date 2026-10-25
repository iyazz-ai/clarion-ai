from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("news", "0007_story_ai_failures"),
    ]

    operations = [
        migrations.CreateModel(
            name="GeminiUsage",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("day", models.CharField(max_length=10)),
                ("model", models.CharField(max_length=100)),
                ("count", models.PositiveIntegerField(default=0)),
            ],
            options={
                "unique_together": {("day", "model")},
            },
        ),
    ]
