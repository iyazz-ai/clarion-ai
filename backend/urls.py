from django.conf import settings
from django.contrib import admin
from django.urls import path

from news.views import FeedView, HealthView, StoryDetailView, StoryListView, TrendingView

urlpatterns = [
    # The admin lives at ADMIN_URL (default "admin/"). In production set a
    # less guessable one in the environment, e.g. ADMIN_URL=manage-7f3k/
    path(settings.ADMIN_URL, admin.site.urls),
    path("api/health/", HealthView.as_view(), name="health"),
    path("api/stories/", StoryListView.as_view(), name="story-list"),
    path("api/stories/<int:pk>/", StoryDetailView.as_view(), name="story-detail"),
    path("api/feed/", FeedView.as_view(), name="feed"),
    path("api/trending/", TrendingView.as_view(), name="trending"),
]
