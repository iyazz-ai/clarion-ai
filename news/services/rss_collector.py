import calendar
import hashlib
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import feedparser
import requests
from bs4 import BeautifulSoup

# kind: "lab" = the company's own blog, "press" = independent coverage.
# Clusters only become meaningful when *independent* sources cover the same
# event, so you need some "press" feeds. I could not test these URLs from my
# sandbox - run `python manage.py collect_news` and check that each feed
# reports a non-zero article count. Dead feeds are skipped, not fatal.
RSS_SOURCES = [
    {"name": "OpenAI", "kind": "lab",
     "url": "https://openai.com/news/rss.xml"},
    {"name": "Google DeepMind", "kind": "lab",
     "url": "https://deepmind.google/blog/rss.xml"},
    {"name": "Hugging Face", "kind": "lab",
     "url": "https://huggingface.co/blog/feed.xml"},

    {"name": "MIT Technology Review", "kind": "press",
     "url": "https://www.technologyreview.com/topic/artificial-intelligence/feed"},
    {"name": "The Verge", "kind": "press",
     "url": "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml"},
    {"name": "TechCrunch", "kind": "press",
     "url": "https://techcrunch.com/category/artificial-intelligence/feed/"},
    # VentureBeat returned HTTP 429 (blocks automated requests) - disabled.
    # {"name": "VentureBeat", "kind": "press",
    #  "url": "https://venturebeat.com/category/ai/feed/"},
]

# Entries WITHOUT a date are kept (never given an invented date) but only the
# newest N per feed, so one big undated feed cannot flood the database.
UNDATED_LIMIT = 20

REQUEST_TIMEOUT = 30
DOWNLOAD_ATTEMPTS = 2
USER_AGENT = "ClarionAI/1.0 (+news aggregator; contact: owner)"

_TRACKING_PARAMS = {"ref", "source", "fbclid", "gclid", "mc_cid", "mc_eid"}


class FeedError(Exception):
    """A feed could not be downloaded or parsed."""


def parse_published_date(item):
    """
    Return a timezone-aware datetime or None.

    Uses feedparser's *_parsed fields first: feedparser already understands
    RSS (RFC 822) AND Atom (ISO 8601) dates. The old code only handled
    RFC 822 strings, so every Atom-style feed would have lost all its dates.
    """
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        parsed = item.get(key)
        if parsed:
            try:
                return datetime.fromtimestamp(
                    calendar.timegm(parsed), tz=timezone.utc
                )
            except (OverflowError, ValueError, TypeError):
                pass

    for key in ("published", "updated"):
        raw = item.get(key)
        if not raw:
            continue
        try:
            date = parsedate_to_datetime(raw)
            if date.tzinfo is None:
                date = date.replace(tzinfo=timezone.utc)
            return date
        except (TypeError, ValueError, IndexError):
            continue

    return None


def extract_image(item):
    """Try the common RSS image formats."""
    for key in ("media_content", "media_thumbnail"):
        for media in item.get(key) or []:
            url = media.get("url")
            if url:
                return url

    for enclosure in item.get("enclosures") or []:
        url = enclosure.get("href") or enclosure.get("url")
        if url and (enclosure.get("type", "").startswith("image") or not enclosure.get("type")):
            return url

    return ""


def clean_html(text):
    """RSS descriptions often contain HTML; Gemini should see plain text."""
    if not text:
        return ""
    plain = BeautifulSoup(text, "html.parser").get_text(" ", strip=True)
    return re.sub(r"\s+", " ", plain).strip()


def canonical_url(url):
    """
    Drop tracking parameters and fragments so the same article is not stored
    twice. Path and trailing slash are left untouched on purpose, so URLs
    already in your database still match.
    """
    parts = urlsplit(url.strip())
    query = [
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not k.lower().startswith("utm_") and k.lower() not in _TRACKING_PARAMS
    ]
    return urlunsplit((
        parts.scheme.lower(), parts.netloc.lower(), parts.path,
        urlencode(query), "",
    ))


def make_content_hash(source_name, title):
    """Stable hash used to catch the same post republished under a new URL."""
    normalised = re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()
    return hashlib.sha256(f"{source_name.lower()}|{normalised}".encode()).hexdigest()


def fetch_feed(source, days=7):
    """
    Download one feed and return its recent entries.
    Raises FeedError on network/parse failure so the caller can report it
    (the old code silently returned 0 articles).
    """
    response = None
    last_error = None
    for attempt in range(DOWNLOAD_ATTEMPTS):
        try:
            response = requests.get(
                source["url"],
                timeout=REQUEST_TIMEOUT,
                headers={"User-Agent": USER_AGENT},
            )
            response.raise_for_status()
            break
        except requests.RequestException as error:
            last_error = error
            response = None

    if response is None:
        raise FeedError(
            f"{source['name']}: download failed after {DOWNLOAD_ATTEMPTS} "
            f"attempts ({last_error})"
        ) from last_error

    feed = feedparser.parse(response.content)

    if getattr(feed, "bozo", False) and not feed.entries:
        raise FeedError(f"{source['name']}: feed could not be parsed")

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    recent = []
    undated_kept = 0
    undated_dropped = 0

    for item in feed.entries:
        published_at = parse_published_date(item)
        if published_at is None:
            # Keep it (published_at stays NULL). It is never grouped with
            # dated stories, and never shown or summarised until it has a
            # real date. Feeds list newest first, so keep the first N only.
            if undated_kept < UNDATED_LIMIT:
                recent.append(item)
                undated_kept += 1
            else:
                undated_dropped += 1
            continue
        if published_at >= cutoff:
            recent.append(item)

    print(
        f"{source['name']}: {len(feed.entries)} in feed, "
        f"{len(recent) - undated_kept} recent dated, "
        f"{undated_kept} undated kept, {undated_dropped} undated skipped"
    )
    return recent
