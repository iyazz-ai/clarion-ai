"""
Rebuild story groups with the current matcher - SAFELY.

    python manage.py regroup_stories            # DRY RUN: reports, changes nothing
    python manage.py regroup_stories --apply    # writes the new grouping

Guarantees
* Dry run is the default and writes nothing.
* Every article is accounted for (checked in the dry run AND after apply).
* Undated articles are never given a date and never grouped with dated ones.
  They are reported, and each ends up in its own single-article story.
* A story keeps its AI summary only if its (dated) article set is unchanged.
  Changed or new stories are marked needs_ai_update.
* Apply runs in one transaction: any failure rolls everything back.
* Nothing is deleted except old stories that end up with zero articles.
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from news.models import Article, Story
from news.services.entity_extractor import extract_entities
from news.services.story_matcher import group_articles


class Plan:
    """What regrouping WOULD do. Built without touching the database."""

    def __init__(self):
        articles = list(Article.objects.select_related("story").order_by("id"))
        self.total = len(articles)
        self.dated = [a for a in articles if a.published_at]
        self.undated = [a for a in articles if not a.published_at]
        self.groups = group_articles(self.dated)

        # existing story id -> set of DATED article ids / all article ids
        self.story_dated, self.story_all = {}, {}
        for a in articles:
            if a.story_id:
                self.story_all.setdefault(a.story_id, set()).add(a.id)
                if a.published_at:
                    self.story_dated.setdefault(a.story_id, set()).add(a.id)

        by_ids = {}
        for sid, ids in self.story_dated.items():
            by_ids.setdefault(frozenset(ids), sid)

        self.keep = {}          # group index -> existing story id
        self.create = []        # group indexes that need a new story
        for i, group in enumerate(self.groups):
            ids = frozenset(a.id for a in group)
            if ids in by_ids:
                self.keep[i] = by_ids[ids]
            else:
                self.create.append(i)

        kept = set(self.keep.values())

        # Undated articles that are NOT the only article of their story are
        # detached into their own stories.
        self.detach = [
            a for a in self.undated
            if a.story_id is None or len(self.story_all.get(a.story_id, ())) > 1
        ]

        # Existing stories that will end up empty (and be deleted): not kept,
        # and no undated article stays in them.
        detach_ids = {a.id for a in self.detach}
        staying_undated = {
            a.story_id for a in self.undated
            if a.story_id and a.id not in detach_ids
        }
        self.obsolete = [
            sid for sid in self.story_all
            if sid not in kept and sid not in staying_undated
        ]
        self.kept_with_undated = [
            sid for sid in kept
            if self.story_all[sid] - self.story_dated.get(sid, set())
        ]

    def accounted_articles(self):
        ids = [a.id for g in self.groups for a in g] + [a.id for a in self.undated]
        return len(ids), len(set(ids))


class Command(BaseCommand):
    help = "Re-cluster all articles with the current matcher (dry run by default)."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true",
                            help="Write the new grouping to the database.")

    def handle(self, *args, **options):
        plan = Plan()
        self._report(plan)

        counted, unique = plan.accounted_articles()
        if counted != plan.total or unique != plan.total:
            raise CommandError(
                f"Accounting error: {plan.total} articles in DB but the plan "
                f"covers {counted} ({unique} unique). Nothing was changed."
            )
        self.stdout.write(self.style.SUCCESS(
            f"\nAccounting check: all {plan.total} articles are covered exactly once."
        ))

        if not options["apply"]:
            self.stdout.write(self.style.WARNING(
                "\nDRY RUN - nothing was changed. Review the report above, then "
                "re-run with --apply."
            ))
            return

        self._apply(plan)

    # ------------------------------------------------------------ report
    def _report(self, plan):
        multi = [g for g in plan.groups if len(g) > 1]
        unassigned_undated = sum(1 for a in plan.undated if a.story_id is None)

        self.stdout.write(
            f"Articles: {plan.total} total = {len(plan.dated)} dated + "
            f"{len(plan.undated)} undated ({unassigned_undated} not in any story)"
        )
        self.stdout.write(
            f"Proposed stories from dated articles: {len(plan.groups)} "
            f"({len(multi)} with 2+ articles)"
        )
        self.stdout.write(
            f"  keep unchanged (summary preserved): {len(plan.keep)}\n"
            f"  create new / changed (will need AI): {len(plan.create)}\n"
            f"  old stories to delete (end up empty): {len(plan.obsolete)}\n"
            f"  undated articles to put in their own story: {len(plan.detach)}\n"
            f"  kept stories that lose an undated member: {len(plan.kept_with_undated)}"
        )

        lost_summaries = Story.objects.filter(
            id__in=plan.obsolete).exclude(summary="").count()
        self.stdout.write(
            f"  stories with an AI summary that will be regenerated: {lost_summaries}"
        )

        for group in multi:
            self.stdout.write("\n  GROUP")
            for a in group:
                self.stdout.write(f"    [{a.source}] {a.published_at:%Y-%m-%d}  {a.title}")

        if plan.undated:
            self.stdout.write("\n  UNDATED ARTICLES (never grouped, never given a date):")
            for a in plan.undated[:15]:
                self.stdout.write(f"    [{a.source}] {a.title}")
            if len(plan.undated) > 15:
                self.stdout.write(f"    ... and {len(plan.undated) - 15} more")

        changed = [i for i in plan.create if len(plan.groups[i]) > 0]
        if changed:
            self.stdout.write("\n  STORIES WHOSE MEMBERSHIP CHANGES (first 15):")
            for i in changed[:15]:
                self.stdout.write(
                    f"    new story of {len(plan.groups[i])} article(s): "
                    f"{plan.groups[i][0].title[:80]}"
                )

    # ------------------------------------------------------------- apply
    @transaction.atomic
    def _apply(self, plan):
        before_total = Article.objects.count()
        kept_ids = set(plan.keep.values())

        def new_story(articles, needs_ai=True):
            dated = [a for a in articles if a.published_at]
            first = min(dated, key=lambda a: a.published_at) if dated else articles[0]
            entities = set()
            for a in articles:
                entities |= extract_entities(a.title)
            story = Story.objects.create(
                title=first.title,
                first_published_at=first.published_at,    # None for undated: no invented date
                entities=sorted(entities),
                needs_ai_update=needs_ai,
            )
            Article.objects.filter(id__in=[a.id for a in articles]).update(story=story)
            return story

        # 1. new / changed groups
        for i in plan.create:
            new_story(plan.groups[i])

        # 2. undated articles -> their own story
        for article in plan.detach:
            new_story([article])

        # 3. kept stories that lost an undated member must be re-summarised
        for sid in plan.kept_with_undated:
            Story.objects.filter(id=sid).update(needs_ai_update=True)

        # 4. delete ONLY stories that are now empty
        empty = Story.objects.exclude(id__in=kept_ids).filter(articles__isnull=True)
        deleted = empty.count()
        empty.delete()

        # 5. final safety check - any failure here rolls everything back
        if Article.objects.count() != before_total:
            raise CommandError("Article count changed - rolled back.")
        if Article.objects.filter(story__isnull=True).exists():
            raise CommandError("Some articles ended up without a story - rolled back.")

        self.stdout.write(self.style.SUCCESS(
            f"\nApplied: kept {len(kept_ids)} stories, created "
            f"{len(plan.create) + len(plan.detach)}, deleted {deleted} empty ones. "
            f"All {before_total} articles preserved."
        ))
