from django.core.management.base import BaseCommand

from news.models import Article
from news.services.ai_processor import process_article


class Command(BaseCommand):
    help = "Process unprocessed articles using Gemini."

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=5,
            help="Maximum number of articles to process.",
        )

    def handle(self, *args, **options):

        limit = options["limit"]

        articles = (
            Article.objects
            .exclude(description="")
            .filter(summary="")
            .order_by("-published_at")[:limit]
        )

        total = articles.count()

        self.stdout.write(
            self.style.SUCCESS(
                f"Found {total} unprocessed articles to process."
            )
        )

        processed = 0
        failed = 0

        for article in articles:

            self.stdout.write(
                f"\nProcessing: {article.title}"
            )

            try:
                process_article(article)

                processed += 1

                self.stdout.write(
                    self.style.SUCCESS(
                        "✓ Processed successfully"
                    )
                )

            except Exception as error:

                failed += 1

                self.stdout.write(
                    self.style.ERROR(
                        f"✗ Failed: {error}"
                    )
                )

        self.stdout.write("\n" + "=" * 50)

        self.stdout.write(
            self.style.SUCCESS(
                f"Processed: {processed}"
            )
        )

        self.stdout.write(
            self.style.ERROR(
                f"Failed: {failed}"
            )
        )

        self.stdout.write("=" * 50)