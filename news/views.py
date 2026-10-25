from django.db import connection
from django.db.models import Prefetch
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_control, never_cache
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from news.models import Article, Story
from news.serializers import StoryDetailSerializer, StorySerializer
from news.services.feed_scoring import apply_feed_score
from news.services.story_query import get_story_queryset
from news.services.trending import TRENDING_LIMIT, get_trending_stories

PAGE_SIZE = 10

# Public, read-only data: let browsers and CDNs reuse a response for a minute.
cache_a_minute = method_decorator(cache_control(public=True, max_age=60), name="get")


def paginate(request, queryset):
    """Shared pagination (was copy-pasted three times). Returns a Response."""
    try:
        page = int(request.query_params.get("page", "1"))
    except ValueError:
        return Response({"detail": "page must be a number."},
                        status=status.HTTP_400_BAD_REQUEST)
    if page < 1:
        return Response({"detail": "page must be greater than 0."},
                        status=status.HTTP_400_BAD_REQUEST)

    total_count = queryset.count()
    start = (page - 1) * PAGE_SIZE
    serializer = StorySerializer(queryset[start:start + PAGE_SIZE], many=True)

    return Response({
        "count": total_count,
        "page": page,
        "page_size": PAGE_SIZE,
        "total_pages": (total_count + PAGE_SIZE - 1) // PAGE_SIZE,
        "results": serializer.data,
    })


@cache_a_minute
class StoryListView(APIView):
    def get(self, request):
        try:
            stories = get_story_queryset(request.query_params)
        except ValueError as error:
            return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)
        return paginate(request, stories)


@cache_a_minute
class FeedView(APIView):
    """Ranked feed. ?sort=top (default) | latest | important"""

    def get(self, request):
        try:
            stories = get_story_queryset(request.query_params)
        except ValueError as error:
            return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)

        sort = request.query_params.get("sort", "top")
        return paginate(request, apply_feed_score(stories, sort))


@cache_a_minute
class StoryDetailView(APIView):
    def get(self, request, pk):
        try:
            story = (
                Story.objects
                .prefetch_related(Prefetch(
                    "articles", queryset=Article.objects.order_by("-published_at")
                ))
                .get(pk=pk, summary__gt="")
            )
        except Story.DoesNotExist:
            return Response({"detail": "Story not found."},
                            status=status.HTTP_404_NOT_FOUND)
        return Response(StoryDetailSerializer(story).data)


@cache_a_minute
class TrendingView(APIView):
    def get(self, request):
        # a short list (the filters live inside get_trending_stories)
        stories = get_trending_stories()[:TRENDING_LIMIT]
        return paginate(request, stories)


@method_decorator(never_cache, name="get")
class HealthView(APIView):
    """For uptime monitors and the hosting platform: is the app + database up?"""

    authentication_classes = []
    permission_classes = []
    throttle_classes = []

    def get(self, request):
        try:
            connection.ensure_connection()
            Story.objects.exists()
        except Exception:
            return Response({"status": "database unavailable"},
                            status=status.HTTP_503_SERVICE_UNAVAILABLE)
        return Response({"status": "ok"})
