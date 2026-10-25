from django.db import transaction

from news.models import Story
from news.services.entity_extractor import extract_entities
from news.services.story_matcher import find_matching_story


@transaction.atomic
def create_or_assign_story(article):
    """
    Attach `article` to a matching story, or start a new one.
    Returns (story, was_created, score).
    """
    story, score = find_matching_story(article)
    article_entities = extract_entities(article.title)

    if story:
        article.story = story
        article.save(update_fields=["story"])

        update_fields = ["needs_ai_update", "ai_failures"]

        # New coverage -> the summary must be regenerated.
        # (The old code never did this, so summaries went stale.)
        story.needs_ai_update = True
        story.ai_failures = 0

        merged = set(story.entities or []) | article_entities
        if merged != set(story.entities or []):
            story.entities = sorted(merged)
            update_fields.append("entities")

        if article.published_at and (
            not story.first_published_at
            or article.published_at < story.first_published_at
        ):
            story.first_published_at = article.published_at
            update_fields.append("first_published_at")

        story.save(update_fields=update_fields)
        return story, False, score

    story = Story.objects.create(
        title=article.title,
        first_published_at=article.published_at,
        entities=sorted(article_entities),
        needs_ai_update=True,
    )
    article.story = story
    article.save(update_fields=["story"])
    return story, True, 0.0
