from datetime import timedelta

from django.db.models import Case, Count, FloatField, Max, Value, When
from django.utils import timezone

FEED_WINDOW_DAYS = 14

# Stories Gemini rated below this are noise (ads, promos, off-topic) and are
# hidden from the Feed and Trending. They stay in the database.
MIN_FEED_IMPORTANCE = 15

# ?sort=...   (what the frontend sends)
SORT_TOP = "top"
SORT_LATEST = "latest"
SORT_IMPORTANT = "important"

# Top stories = 45% importance + 40% freshness + 15% corroboration.
# Freshness is deliberately strong: this page is "Today in AI", so a 6-day-old
# story must not outrank something published this morning.
W_IMPORTANCE, W_FRESHNESS, W_CORROBORATION = 0.45, 0.40, 0.15

# (max age in hours, freshness points)
FRESHNESS_STEPS = [
    (6, 100.0), (12, 95.0), (24, 85.0), (48, 65.0),
    (72, 45.0), (120, 25.0), (168, 10.0),
]


def freshness_case(now, field="latest_article_at"):
    """SQL CASE giving 0-100 points for how recent `field` is."""
    whens = [
        When(**{f"{field}__gte": now - timedelta(hours=hours)}, then=Value(points))
        for hours, points in FRESHNESS_STEPS
    ]
    return Case(*whens, default=Value(0.0), output_field=FloatField())


def corroboration_case(count_field="source_count"):
    """SQL CASE giving 0-100 points for how many different sources cover a story."""
    return Case(
        When(**{f"{count_field}__gte": 4}, then=Value(100.0)),
        When(**{f"{count_field}__gte": 3}, then=Value(80.0)),
        When(**{f"{count_field}__gte": 2}, then=Value(60.0)),
        default=Value(20.0),
        output_field=FloatField(),
    )


def apply_feed_score(stories, sort=SORT_TOP):
    """
    Annotate and order stories for the Feed.

    The old version always ended with order_by("-feed_score"), which silently
    overrode the ?sort= parameter the frontend sends.
    """
    now = timezone.now()
    window = now - timedelta(days=FEED_WINDOW_DAYS)

    stories = stories.annotate(
        latest_article_at=Max("articles__published_at"),
        article_count=Count("articles", distinct=True),
        source_count=Count("articles__source", distinct=True),
    ).filter(
        latest_article_at__gte=window,
        importance_score__gte=MIN_FEED_IMPORTANCE,
    )

    stories = stories.annotate(
        freshness_score=freshness_case(now),
        corroboration_score=corroboration_case(),
    )

    stories = stories.annotate(
        feed_score=(
            Value(W_IMPORTANCE) * Case(
                When(importance_score__isnull=False, then="importance_score"),
                default=Value(0.0),
                output_field=FloatField(),
            )
            + Value(W_FRESHNESS) * Case(
                When(latest_article_at__isnull=False, then="freshness_score"),
                default=Value(0.0),
                output_field=FloatField(),
            )
            + Value(W_CORROBORATION) * Case(
                When(latest_article_at__isnull=False, then="corroboration_score"),
                default=Value(0.0),
                output_field=FloatField(),
            )
        )
    )

    if sort == SORT_LATEST:
        return stories.order_by("-latest_article_at", "-feed_score")
    if sort == SORT_IMPORTANT:
        return stories.order_by("-importance_score", "-latest_article_at")
    return stories.order_by("-feed_score", "-latest_article_at")
