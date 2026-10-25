import html
import re

from django.core.management.base import BaseCommand, CommandError

from news.models import Article
from news.services.rss_collector import (
    RSS_SOURCES,
    FeedError,
    canonical_url,
    clean_html,
    extract_image,
    fetch_feed,
    make_content_hash,
    parse_published_date,
)


# invisible characters some feeds put inside titles (word joiner, zero-width space...)
_ZERO_WIDTH = re.compile("[\u200b\u200c\u200d\u2060\ufeff]")


class Command(BaseCommand):
    help = "Collect AI news from RSS feeds"

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS("Starting Clarion news collector..."))

        total_new = 0
        failed_sources = []

        for source in RSS_SOURCES:
            try:
                entries = fetch_feed(source)
            except FeedError as error:
                failed_sources.append(source["name"])
                self.stderr.write(self.style.ERROR(str(error)))
                continue

            new_count = 0
            for item in entries:
                if self._save_item(source, item):
                    new_count += 1

            self.stdout.write(f"{source['name']}: {new_count} new articles")
            total_new += new_count

        self.stdout.write(self.style.SUCCESS(f"Total new articles: {total_new}"))

        if failed_sources:
            self.stderr.write(
                self.style.WARNING(f"Failed feeds: {', '.join(failed_sources)}")
            )
        # Only fail the whole command if NOTHING could be collected.
        if failed_sources and len(failed_sources) == len(RSS_SOURCES):
            raise CommandError("All feeds failed.")

    def _save_item(self, source, item):
        """Store one feed item. Returns True if a new Article was created."""
        title = _ZERO_WIDTH.sub("", html.unescape((item.get("title") or ""))).strip()
        raw_url = (item.get("link") or "").strip()
        if not title or not raw_url:
            return False

        url = canonical_url(raw_url)
        content_hash = make_content_hash(source["name"], title)

        # Same URL, or same title from the same source under a new URL.
        existing = (
            Article.objects.filter(url=url).first()
            or Article.objects.filter(url=raw_url).first()
            or Article.objects.filter(content_hash=content_hash).first()
        )

        published_at = parse_published_date(item)
        author = (item.get("author") or "").strip()
        image_url = extract_image(item)

        if existing is None:
            Article.objects.create(
                url=url,
                title=title[:500],
                description=clean_html(item.get("summary") or ""),
                source=source["name"],
                author=author[:200],
                published_at=published_at,
                image_url=image_url,
                content_hash=content_hash,
            )
            return True

        # Fill in anything that was missing on an existing row.
        changed = []
        if not existing.author and author:
            existing.author = author[:200]
            changed.append("author")
        if not existing.published_at and published_at:
            existing.published_at = published_at
            changed.append("published_at")
            # An undated article was alone in a story with no date: give the
            # story the real date now that we have one.
            story = existing.story
            if story and story.first_published_at is None:
                story.first_published_at = published_at
                story.save(update_fields=["first_published_at"])
        if not existing.image_url and image_url:
            existing.image_url = image_url
            changed.append("image_url")
        if not existing.content_hash:
            existing.content_hash = content_hash
            changed.append("content_hash")
        if changed:
            existing.save(update_fields=changed)
        return False
