import time
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db.models import F, Max
from django.utils import timezone

from news.models import Story
from news.services.gemini_client import QuotaExceeded, usage_summary
from news.services.story_ai_processor import IncoherentStory, process_batch

PARK_AFTER_FAILURES = 3


class Command(BaseCommand):
    help = "Generate AI intelligence for Stories that need updating."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=20,
                            help="Maximum number of STORIES to process (0 = all).")
        parser.add_argument("--batch-size", type=int, default=5,
                            help="Stories per Gemini request. Higher = fewer "
                                 "requests (good for free-tier daily limits).")
        parser.add_argument("--delay", type=float, default=0.0,
                            help="Extra seconds between requests. Rate limits are "
                                 "already paced by the Gemini client.")
        parser.add_argument("--retry-failed", action="store_true",
                            help="Also retry stories that failed 3+ times.")

    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(days=14)

        stories = (
            Story.objects
            .filter(needs_ai_update=True)
            .annotate(latest_article_at=Max("articles__published_at"))
            .filter(latest_article_at__gte=cutoff)
        )
        if not options["retry_failed"]:
            stories = stories.filter(ai_failures__lt=PARK_AFTER_FAILURES)

        stories = stories.order_by("ai_failures", "-latest_article_at")
        if options["limit"] > 0:
            stories = stories[: options["limit"]]
        stories = list(stories)

        size = max(1, options["batch_size"])
        batches = [stories[i:i + size] for i in range(0, len(stories), size)]

        self.stdout.write(
            f"Found {len(stories)} stories -> {len(batches)} Gemini request(s)."
        )
        self.stdout.write(usage_summary())

        processed = failed = 0
        for index, batch in enumerate(batches):
            if index:
                time.sleep(options["delay"])

            self.stdout.write(f"\nRequest {index + 1}/{len(batches)}: "
                              f"{len(batch)} stories")
            try:
                results = process_batch(batch)
            except QuotaExceeded as error:
                # NOT the stories' fault: do not count a failure, just stop.
                self.stderr.write(self.style.WARNING(
                    "Gemini quota reached - stopping. Remaining stories stay "
                    "queued for the next run.\n" + str(error)[:200]
                ))
                break
            except Exception as error:
                failed += len(batch)
                Story.objects.filter(pk__in=[s.pk for s in batch]).update(
                    ai_failures=F("ai_failures") + 1
                )
                self.stderr.write(self.style.ERROR(f"  request failed: {error}"))
                continue

            for story in batch:
                error = results.get(story.pk)
                if error is None:
                    processed += 1
                    self.stdout.write(self.style.SUCCESS(f"  ok: {story.title[:70]}"))
                elif isinstance(error, IncoherentStory):
                    failed += 1
                    Story.objects.filter(pk=story.pk).update(
                        ai_failures=PARK_AFTER_FAILURES
                    )
                    self.stderr.write(self.style.WARNING(
                        f"  needs review (split in admin): {story.title[:70]}"))
                else:
                    failed += 1
                    Story.objects.filter(pk=story.pk).update(
                        ai_failures=F("ai_failures") + 1
                    )
                    self.stderr.write(self.style.ERROR(
                        f"  failed: {story.title[:60]} -> {error}"))

        self.stdout.write(f"\nProcessed: {processed}  Failed: {failed}")
