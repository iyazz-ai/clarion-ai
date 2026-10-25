from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("news", "0006_story_entities"),
    ]

    operations = [
        migrations.AddField(
            model_name="story",
            name="ai_failures",
            field=models.PositiveSmallIntegerField(default=0),
        ),
    ]
