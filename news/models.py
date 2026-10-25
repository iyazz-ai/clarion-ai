from django.db import models


class Article(models.Model):
    title = models.CharField(max_length=500)
    story = models.ForeignKey(
        "Story",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="articles",
    )
    description = models.TextField(blank=True)
    url = models.URLField(unique=True)
    source = models.CharField(max_length=200)
    author = models.CharField(max_length=200, blank=True)

    published_at = models.DateTimeField(null=True, blank=True)

    category = models.CharField(max_length=100, blank=True)

    image_url = models.URLField(blank=True)

    content_hash = models.CharField(
        max_length=64,
        unique=True,
        null=True,
        blank=True,
    )

    summary = models.TextField(blank=True)
    why_it_matters = models.TextField(blank=True)

    importance_score = models.FloatField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title


class Story(models.Model):
    title = models.CharField(max_length=500)

    entities = models.JSONField(default=list, blank=True)
    first_published_at = models.DateTimeField(null=True, blank=True)

    summary = models.TextField(blank=True)
    why_it_matters = models.TextField(blank=True)
    category = models.CharField(max_length=100, blank=True)
    importance_score = models.FloatField(null=True, blank=True)

    needs_ai_update = models.BooleanField(default=True)

    # NEW: how many times Gemini processing failed in a row. Stories that keep
    # failing are skipped so they cannot block the queue forever.
    ai_failures = models.PositiveSmallIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title


class GeminiUsage(models.Model):
    """
    How many Gemini requests were sent per model per (Pacific) day. Stored in
    the database, not in a file, so the daily-budget guard also works on
    hosts whose disk is wiped between runs (GitHub Actions, Render...).
    """

    day = models.CharField(max_length=10)
    model = models.CharField(max_length=100)
    count = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = [("day", "model")]

    def __str__(self):
        return f"{self.day} {self.model}: {self.count}"
