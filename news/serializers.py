from rest_framework import serializers

from news.models import Article, Story


class StoryArticleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Article
        fields = ["id", "title", "source", "author", "published_at", "url", "image_url"]


class StorySerializer(serializers.ModelSerializer):
    # All three are computed from the prefetched articles, so a page of
    # stories costs 2 queries instead of 1 + 2 per story.
    article_count = serializers.SerializerMethodField()
    sources = serializers.SerializerMethodField()
    latest_article_at = serializers.SerializerMethodField()

    trending_score = serializers.FloatField(read_only=True)

    def get_article_count(self, story):
        return len(story.articles.all())

    def get_sources(self, story):
        return sorted({a.source for a in story.articles.all()})

    def get_latest_article_at(self, story):
        annotated = getattr(story, "latest_article_at", None)
        if annotated:
            return annotated
        dates = [a.published_at for a in story.articles.all() if a.published_at]
        return max(dates) if dates else None

    class Meta:
        model = Story
        fields = [
            "id", "title", "first_published_at", "summary", "why_it_matters",
            "category", "importance_score", "article_count", "sources",
            "latest_article_at", "trending_score",
        ]


class StoryDetailSerializer(StorySerializer):
    articles = StoryArticleSerializer(many=True, read_only=True)

    class Meta(StorySerializer.Meta):
        fields = StorySerializer.Meta.fields + ["articles"]
