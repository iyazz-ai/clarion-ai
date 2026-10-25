from django.core.management.base import BaseCommand

from news.models import Article
from news.services.rss_collector import (
    RSS_SOURCES,
    parse_published_date,
    extract_image,
)

import feedparser


class Command(BaseCommand):

    help = "Backfill missing metadata for existing articles"

    def handle(self, *args, **options):

        self.stdout.write(
            self.style.SUCCESS(
                "Starting metadata backfill..."
            )
        )

        total_updated = 0

        for source in RSS_SOURCES:

            self.stdout.write(
                f"Fetching {source['name']}..."
            )

            feed = feedparser.parse(source["url"])

            updated_count = 0

            for item in feed.entries:

                url = item.get("link", "").strip()

                if not url:
                    continue

                try:
                    article = Article.objects.get(
                        url=url
                    )
                except Article.DoesNotExist:
                    continue

                changed = False

                # Published date
                if article.published_at is None:

                    published_at = parse_published_date(item)

                    if published_at:
                        article.published_at = published_at
                        changed = True

                # Author
                if not article.author:

                    author = item.get(
                        "author",
                        ""
                    ).strip()

                    if author:
                        article.author = author
                        changed = True

                # Image
                if not article.image_url:

                    image_url = extract_image(item)

                    if image_url:
                        article.image_url = image_url
                        changed = True

                if changed:

                    article.save()

                    updated_count += 1
                    total_updated += 1

            self.stdout.write(
                f"{source['name']}: "
                f"{updated_count} articles updated"
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Total articles updated: "
                f"{total_updated}"
            )
        )