from django.core.management.base import BaseCommand
from django.db.models import Min

from news.models import Story


class Command(BaseCommand):
    help = "Fill missing story first_published_at from the earliest article."

    def handle(self, *args, **options):
        stories = Story.objects.filter(first_published_at__isnull=True)

        updated = 0

        for story in stories:
            first_date = story.articles.aggregate(
                first_published_at=Min("published_at")
            )["first_published_at"]

            if first_date:
                story.first_published_at = first_date
                story.save(update_fields=["first_published_at"])
                updated += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Updated {updated} stories."
            )
        )