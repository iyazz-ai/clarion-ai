from datetime import timedelta

from django.db.models import (
    Case,
    Count,
    ExpressionWrapper,
    F,
    FloatField,
    Max,
    Prefetch,
    Value,
    When,
)
from django.utils import timezone

from news.models import Article, Story
from news.services.feed_scoring import corroboration_case, freshness_case

# Trending = "what is moving RIGHT NOW": a short list, last two days only.
TRENDING_WINDOW_HOURS = 48
# On a quiet news day (or when the update job has not run for a while) fewer
# than this many stories would make the page look broken, so the window widens.
MIN_TRENDING_ITEMS = 8
TRENDING_FALLBACK_HOURS = 120
TRENDING_LIMIT = 20
MIN_TRENDING_IMPORTANCE = 30

W_FRESHNESS, W_IMPORTANCE, W_CORROBORATION = 0.40, 0.35, 0.25


def get_trending_stories():
    stories = _build(TRENDING_WINDOW_HOURS)
    if stories.count() < MIN_TRENDING_ITEMS:
        stories = _build(TRENDING_FALLBACK_HOURS)
    return stories


def _build(window_hours):
    """
    AI-processed stories ranked by recent momentum.

    trending_score = 40% freshness + 35% importance + 25% coverage
    Coverage = how many different sources report it, plus a bonus when a
    story has many articles (a big launch with several posts).
    The view caps the result at TRENDING_LIMIT stories.
    """
    now = timezone.now()
    cutoff = now - timedelta(hours=window_hours)

    stories = (
        Story.objects
        .exclude(summary="")
        .prefetch_related(
            Prefetch("articles", queryset=Article.objects.order_by("-published_at"))
        )
        .annotate(
            latest_article_at=Max("articles__published_at"),
            article_count_score=Count("articles", distinct=True),
            source_count_score=Count("articles__source", distinct=True),
        )
        .filter(
            latest_article_at__gte=cutoff,
            importance_score__gte=MIN_TRENDING_IMPORTANCE,
        )
        .annotate(
            freshness_score=freshness_case(now),
            coverage_score=ExpressionWrapper(
                corroboration_case("source_count_score")
                + Case(
                    When(article_count_score__gte=4, then=Value(20.0)),
                    default=Value(0.0),
                    output_field=FloatField(),
                ),
                output_field=FloatField(),
            ),
        )
    )

    stories = stories.annotate(
        trending_score=ExpressionWrapper(
            Value(W_FRESHNESS) * F("freshness_score")
            + Value(W_IMPORTANCE) * F("importance_score")
            + Value(W_CORROBORATION) * Case(
                When(coverage_score__gte=100.0, then=Value(100.0)),
                default=F("coverage_score"),
                output_field=FloatField(),
            ),
            output_field=FloatField(),
        )
    )

    return stories.order_by("-trending_score", "-latest_article_at")
