"""One-off cleanup: turn &#8216; style HTML entities in stored titles into real characters."""

import html
import re

from django.core.management.base import BaseCommand

from news.models import Article, Story


_ZERO_WIDTH = re.compile("[\u200b\u200c\u200d\u2060\ufeff]")


class Command(BaseCommand):
    help = "Decode HTML entities and remove invisible characters in stored titles."

    def handle(self, *args, **options):
        fixed = 0
        for model in (Article, Story):
            for obj in model.objects.all():
                clean = _ZERO_WIDTH.sub("", html.unescape(obj.title))
                if clean != obj.title:
                    obj.title = clean
                    obj.save(update_fields=["title"])
                    fixed += 1
        self.stdout.write(self.style.SUCCESS(f"Fixed {fixed} titles."))
