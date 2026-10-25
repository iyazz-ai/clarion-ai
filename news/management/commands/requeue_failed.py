"""
Review / rescue stories that were "parked" after repeated AI failures.

Before v13, temporary Gemini outages (HTTP 503) were counted as story
failures, so a few bad runs could park perfectly good stories.

    python manage.py requeue_failed            # LIST parked stories, change nothing
    python manage.py requeue_failed --apply    # re-queue the SAFE ones

Safe = single-article stories (they cannot be "two different events", so the
failure can only have been technical). Multi-article stories that were parked
may have been flagged by Gemini as mixed events, so they are only listed -
review them in the admin and use "Split selected stories" if needed.
"""

from django.core.management.base import BaseCommand
from django.db.models import Count

from news.models import Story

PARKED_AT = 3


class Command(BaseCommand):
    help = "List parked stories; with --apply re-queue the single-article ones."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        parked = (
            Story.objects.filter(ai_failures__gte=PARKED_AT, summary="")
            .annotate(n=Count("articles"))
        )
        single = [s for s in parked if s.n <= 1]
        multi = [s for s in parked if s.n > 1]

        self.stdout.write(
            f"Parked stories without a summary: {len(single) + len(multi)}\n"
            f"  single-article (safe to retry): {len(single)}\n"
            f"  multi-article (review in admin): {len(multi)}"
        )
        for story in multi:
            self.stdout.write(f"    review: [{story.n} articles] {story.title[:80]}")

        if not options["apply"]:
            self.stdout.write("\nNothing changed. Re-run with --apply to re-queue the safe ones.")
            return

        ids = [s.pk for s in single]
        Story.objects.filter(pk__in=ids).update(ai_failures=0, needs_ai_update=True)
        self.stdout.write(self.style.SUCCESS(f"\nRe-queued {len(ids)} single-article stories."))
