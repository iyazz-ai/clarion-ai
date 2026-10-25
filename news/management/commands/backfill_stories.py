from django.core.management.base import BaseCommand

from news.models import Article
from news.services.story_builder import create_or_assign_story


class Command(BaseCommand):
    help = "Group existing unassigned articles into stories without using AI."

    def handle(self, *args, **options):
        articles = (
            Article.objects
            .filter(story__isnull=True)
            .order_by("published_at", "id")
        )

        total = articles.count()

        self.stdout.write(
            self.style.SUCCESS(
                f"Found {total} unassigned articles."
            )
        )

        created = 0
        assigned = 0

        for index, article in enumerate(articles.iterator(), start=1):

            story, was_created, score = create_or_assign_story(article)

            if was_created:
                created += 1
            else:
                assigned += 1

            if index % 100 == 0 or index == total:
                self.stdout.write(
                    f"Processed {index}/{total} | "
                    f"New stories: {created} | "
                    f"Grouped: {assigned}"
                )

        self.stdout.write(
            self.style.SUCCESS(
                "\nStory backfill completed."
            )
        )

        self.stdout.write(
            f"New stories created: {created}"
        )

        self.stdout.write(
            f"Articles grouped into existing stories: {assigned}"
        )