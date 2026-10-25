from django.contrib import admin, messages
from django.db import transaction
from django.db.models import Count

from news.models import Article, Story


@admin.register(Article)
class ArticleAdmin(admin.ModelAdmin):
    list_display = ("title", "source", "published_at", "story")
    search_fields = ("title", "description", "source")
    list_filter = ("source", "category")
    raw_id_fields = ("story",)


@admin.action(description="Split selected stories (one story per article)")
def split_stories(modeladmin, request, queryset):
    """Manual fix for a wrongly merged story."""
    split = 0
    with transaction.atomic():
        for story in queryset:
            articles = list(story.articles.all())
            if len(articles) < 2:
                continue
            for article in articles:
                new_story = Story.objects.create(
                    title=article.title,
                    first_published_at=article.published_at,
                    needs_ai_update=True,
                )
                article.story = new_story
                article.save(update_fields=["story"])
            story.delete()
            split += 1
    messages.success(request, f"Split {split} stories.")


@admin.register(Story)
class StoryAdmin(admin.ModelAdmin):
    list_display = ("title", "category", "importance_score", "articles_total",
                    "needs_ai_update", "ai_failures", "created_at")
    search_fields = ("title", "summary", "why_it_matters")
    list_filter = ("category", "needs_ai_update")
    actions = [split_stories]

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_n=Count("articles"))

    @admin.display(ordering="_n", description="Articles")
    def articles_total(self, story):
        return story._n
