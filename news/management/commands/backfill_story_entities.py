from django.core.management.base import BaseCommand

from news.models import Story
from news.services.entity_extractor import extract_entities


class Command(BaseCommand):

    help = "Backfill entities for existing stories."

    def handle(self, *args, **options):

        stories = Story.objects.all()

        updated = 0

        for story in stories:

            entities = extract_entities(
                story.title
            )

            story.entities = sorted(
                entities
            )

            story.save(
                update_fields=["entities"]
            )

            updated += 1

            self.stdout.write(
                f"Updated Story {story.id}: "
                f"{story.entities}"
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Successfully updated {updated} stories."
            )
        )