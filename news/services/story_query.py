from datetime import date

from django.db.models import Exists, OuterRef, Prefetch, Q

from news.models import Article, Story

ALLOWED_ORDERINGS = {
    "importance_score", "-importance_score",
    "first_published_at", "-first_published_at",
    "created_at", "-created_at",
    "title", "-title",
}


def _parse_date(value, name):
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ValueError(f"{name} must be in YYYY-MM-DD format.")


def get_story_queryset(params):
    """Build the Story queryset from API query parameters."""

    stories = (
        Story.objects
        .exclude(summary="")
        .prefetch_related(
            Prefetch("articles", queryset=Article.objects.order_by("-published_at"))
        )
    )

    search = (params.get("search") or "").strip()
    if search:
        # One OR-ed filter (the old code OR-ed four separate querysets).
        stories = stories.filter(
            Q(title__icontains=search)
            | Q(summary__icontains=search)
            | Q(why_it_matters__icontains=search)
            | Q(category__icontains=search)
        )

    category = params.get("category")
    if category:
        stories = stories.filter(category__iexact=category)

    # Exists() instead of a join: a join would also shrink the Count/Max
    # annotations in the feed to only the matching source's articles.
    source = params.get("source")
    if source:
        stories = stories.filter(Exists(
            Article.objects.filter(story=OuterRef("pk"), source__iexact=source)
        ))

    min_importance = params.get("min_importance")
    if min_importance:
        try:
            stories = stories.filter(importance_score__gte=float(min_importance))
        except ValueError:
            raise ValueError("min_importance must be a number.")

    from_date = params.get("from")
    if from_date:
        stories = stories.filter(
            first_published_at__date__gte=_parse_date(from_date, "from")
        )

    to_date = params.get("to")
    if to_date:
        stories = stories.filter(
            first_published_at__date__lte=_parse_date(to_date, "to")
        )

    sort = params.get("sort")
    if sort == "latest":
        stories = stories.order_by("-first_published_at")
    elif sort == "oldest":
        stories = stories.order_by("first_published_at")
    elif sort == "important":
        stories = stories.order_by("-importance_score", "-first_published_at")
    else:
        ordering = params.get("ordering")
        if ordering in ALLOWED_ORDERINGS:
            stories = stories.order_by(ordering)
        else:
            stories = stories.order_by("-importance_score", "-first_published_at")

    return stories
