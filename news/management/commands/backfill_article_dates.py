import json
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup
from django.core.management.base import BaseCommand
from django.utils.dateparse import parse_datetime

from news.models import Article


def extract_published_date(url):
    try:
        response = requests.get(
            url,
            timeout=15,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/154.0 Safari/537.36"
                )
            },
        )

        response.raise_for_status()

    except requests.RequestException as error:
        print(f"Request failed: {error}")
        return None

    soup = BeautifulSoup(response.text, "html.parser")

    # 1. <time datetime="...">
    time_tag = soup.find("time")

    if time_tag:
        value = time_tag.get("datetime")

        if value:
            parsed = parse_datetime(value)

            if parsed:
                return parsed

    # 2. Common publication-date meta tags
    meta_selectors = [
        ('meta', {"property": "article:published_time"}),
        ('meta', {"itemprop": "datePublished"}),
        ('meta', {"name": "datePublished"}),
        ('meta', {"name": "publishdate"}),
        ('meta', {"name": "pubdate"}),
    ]

    for tag_name, attributes in meta_selectors:
        tag = soup.find(tag_name, attrs=attributes)

        if tag:
            value = tag.get("content")

            if value:
                parsed = parse_datetime(value)

                if parsed:
                    return parsed

    # 3. JSON-LD structured data
    for script in soup.find_all(
        "script",
        type="application/ld+json"
    ):
        try:
            data = json.loads(script.string or script.get_text())

        except (json.JSONDecodeError, TypeError):
            continue

        if isinstance(data, dict):
            candidates = [data]

        elif isinstance(data, list):
            candidates = data

        else:
            candidates = []

        for item in candidates:
            if not isinstance(item, dict):
                continue

            value = item.get("datePublished")

            if value:
                parsed = parse_datetime(value)

                if parsed:
                    return parsed

    return None


class Command(BaseCommand):

    help = "Backfill missing published dates from article webpages."

    def handle(self, *args, **options):

        articles = Article.objects.filter(
            published_at__isnull=True
        ).order_by("id")

        total = articles.count()

        self.stdout.write(
            f"Found {total} articles with missing dates."
        )

        updated = 0
        failed = 0

        for article in articles:

            self.stdout.write(
                f"\nChecking {article.id}: {article.title}"
            )

            published_at = extract_published_date(article.url)

            if published_at is None:
                self.stdout.write(
                    self.style.WARNING(
                        "  Date not found"
                    )
                )
                failed += 1
                continue

            if published_at.tzinfo is None:
                published_at = published_at.replace(
                    tzinfo=timezone.utc
                )

            article.published_at = published_at

            article.save(
                update_fields=["published_at"]
            )

            updated += 1

            self.stdout.write(
                self.style.SUCCESS(
                    f"  Updated: {published_at}"
                )
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"\nCompleted."
            )
        )

        self.stdout.write(
            f"Updated: {updated}"
        )

        self.stdout.write(
            f"Could not find: {failed}"
        )