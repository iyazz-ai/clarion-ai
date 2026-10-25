"""
Read-only review tool: lists pairs of RECENT stories that were NOT merged but
look like they might be the same event, so you can judge by eye whether the
matcher is too strict. Changes nothing.

    python manage.py find_near_duplicates            # last 7 days
    python manage.py find_near_duplicates --days 3 --limit 20
"""

from datetime import timedelta
from itertools import combinations

from django.core.management.base import BaseCommand
from django.utils import timezone

from news.models import Story
from news.models import Article
from news.services.similarity import COMMON_AI_TERMS, TokenRarity, distinctive_tokens
from news.services.story_matcher import MAX_DAYS_APART, days_apart, evaluate_pair


class Command(BaseCommand):
    help = "Show recent stories that share distinctive words but were not merged."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=7)
        parser.add_argument("--limit", type=int, default=30)
        parser.add_argument("--min-shared", type=int, default=2,
                            help="Minimum shared distinctive words to list a pair.")

    def handle(self, *args, **options):
        since = timezone.now() - timedelta(days=options["days"])
        stories = list(
            Story.objects.filter(first_published_at__gte=since)
            .prefetch_related("articles")
        )

        rarity = TokenRarity(
            Article.objects.filter(published_at__gte=since - timedelta(days=30))
            .values_list("title", flat=True)
        )
        pairs = []
        for a, b in combinations(stories, 2):
            for x in a.articles.all():
                for y in b.articles.all():
                    gap = days_apart(x.published_at, y.published_at)
                    if gap is None or gap > MAX_DAYS_APART:
                        continue
                    shared = (distinctive_tokens(x.title) & distinctive_tokens(y.title)) \
                        - COMMON_AI_TERMS
                    if len(shared) >= options["min_shared"] and not evaluate_pair(x, y, rarity).matched:
                        pairs.append((len(shared), sorted(shared), x, y))

        pairs.sort(key=lambda p: -p[0])
        self.stdout.write(f"{len(stories)} recent stories; "
                          f"{len(pairs)} possible missed merges (showing top {options['limit']}).\n")
        for count, shared, x, y in pairs[: options["limit"]]:
            self.stdout.write(f"shared words: {', '.join(shared)}")
            self.stdout.write(f"  [{x.source}] {x.title}")
            self.stdout.write(f"  [{y.source}] {y.title}\n")
        self.stdout.write("Read-only: nothing was changed.")
