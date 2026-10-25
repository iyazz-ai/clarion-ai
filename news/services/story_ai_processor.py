import math

from news.services.gemini_client import generate_json

ALLOWED_CATEGORIES = {
    "Models", "Agents", "Research", "Products",
    "Business", "Developer Tools", "Safety", "Other",
}

MAX_ARTICLES_PER_STORY = 4

# Output limits (the prompt asks for much less; these reject runaway output)
MAX_HEADLINE_CHARS = 140
MAX_SUMMARY_CHARS = 600
MAX_WHY_CHARS = 400
DESCRIPTION_CHARS = 500


class IncoherentStory(ValueError):
    """Gemini says the grouped articles are not about one event."""


def _story_block(number, story, articles):
    lines = [f"=== STORY {number} ==="]
    for article in articles:
        lines.append(
            f"- [{article.source}] {article.title}\n"
            f"  {(article.description or '')[:DESCRIPTION_CHARS]}"
        )
    return "\n".join(lines)


def _build_prompt(blocks, multi_numbers):
    same_event_line = (
        '      "same_event": true,\n' if multi_numbers else ""
    )
    multi_rule = (
        f"- Stories {sorted(multi_numbers)} contain more than one article. For "
        'THOSE stories you MUST include "same_event" (a JSON boolean): true '
        "only if ALL their articles describe one single development, false if "
        "any article is about a different event. Never omit it for them.\n"
        if multi_numbers else ""
    )
    return f"""
You are the editor of an AI news product. Analyse EACH story below
independently.

{chr(10).join(blocks)}

Return ONLY valid JSON with exactly this structure (one entry per story):

{{
  "stories": [
    {{
      "story": 1,
{same_event_line}      "headline": "Clear neutral headline about the EVENT, max 90 characters",
      "summary": "1-2 sentences, max 40 words, what happened",
      "why_it_matters": "One sentence, max 25 words, concrete significance",
      "category": "Models, Agents, Research, Products, Business, Developer Tools, Safety, or Other",
      "ai_related": true,
      "importance_score": 0
    }}
  ]
}}

Rules:
- Base everything ONLY on the articles of that story. Do not invent facts,
  names, numbers or product names that are not in the articles.
- category must be exactly one of the allowed values.
- importance_score is a number 0-100. Be HARSH: a normal day has at most one
  story above 80, and most stories score between 20 and 60. Anchors:
    95  new frontier-model generation (GPT-5 class launch), landmark regulation
    80  flagship product/model release from a major lab, $10B+ deal
    60  notable startup funding round, notable research result, major
        company AI product update
    40  incremental update, partnership, analysis/report, contained incident
    20  opinion, commentary, small feature, customer case study
     5  ad, promotion, event ticket, or not really about AI
  A funding round or valuation is never above 65 unless it is over $10B.
  Event ads, ticket/discount promotions, newsletters, celebrity or lifestyle
  items and anything not really about AI technology, products, research,
  policy or the AI business must score 0-10.
- ai_related (JSON boolean): false if the story is NOT about AI technology, AI
  products, AI research, AI policy or the AI industry (for example video
  games, film/TV, event registration or ticket deadlines, general tech gossip).
- headline: describe what happened. NEVER start with or mention the
  publisher's name (no "TechCrunch ...", "MIT Tech Review ...", "The Verge ...").
{multi_rule}"""


def _text_field(data, field, max_chars, required=True):
    value = data.get(field)
    if value is None and not required:
        return ""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"'{field}' is missing, empty or not text.")
    value = value.strip()
    if len(value) > max_chars:
        raise ValueError(f"'{field}' is too long ({len(value)} > {max_chars}).")
    return value


def _validate_and_save(story, data, article_count):
    """
    Validate EVERYTHING first, then save. Any problem raises, and the story
    keeps whatever good summary it already had.
    """
    if not isinstance(data, dict):
        raise ValueError("Story entry is not a JSON object.")

    # Multi-article stories need an explicit, boolean coherence verdict.
    # Missing / malformed is NOT approval.
    if article_count > 1:
        same_event = data.get("same_event")
        if not isinstance(same_event, bool):
            raise ValueError(
                "Gemini did not return a valid 'same_event' true/false for a "
                "multi-article story."
            )
        if same_event is False:
            raise IncoherentStory(
                "Gemini says these articles are not one event - split it in the admin."
            )

    summary = _text_field(data, "summary", MAX_SUMMARY_CHARS)
    why = _text_field(data, "why_it_matters", MAX_WHY_CHARS)
    headline = _text_field(data, "headline", MAX_HEADLINE_CHARS, required=False)

    category = data.get("category")
    if category not in ALLOWED_CATEGORIES:
        raise ValueError(f"Invalid category returned by Gemini: {category!r}")

    raw_score = data.get("importance_score")
    if isinstance(raw_score, bool):
        raise ValueError("Importance score must be a number.")
    try:
        importance = float(raw_score)
    except (TypeError, ValueError) as error:
        raise ValueError("Importance score must be a number.") from error
    if not math.isfinite(importance) or not 0 <= importance <= 100:
        raise ValueError("Importance score must be between 0 and 100.")

    # Off-topic stories are pushed below the Feed threshold (they stay in the
    # database). A missing flag is NOT an error - it simply changes nothing.
    if data.get("ai_related") is False:
        importance = min(importance, 5.0)

    # ---- everything is valid: now (and only now) write to the database ----
    if headline:
        story.title = headline[:500]
    story.summary = summary
    story.why_it_matters = why
    story.category = category
    story.importance_score = importance
    story.needs_ai_update = False
    story.ai_failures = 0
    story.save(update_fields=[
        "title", "summary", "why_it_matters", "category",
        "importance_score", "needs_ai_update", "ai_failures",
    ])


def process_batch(stories):
    """
    Summarise several stories with ONE Gemini request (free tiers limit
    requests per day, not tokens, so batching multiplies what you can do).

    Returns {story.pk: None | Exception}. A QuotaExceeded error from the
    API call itself is raised to the caller.
    """
    results, blocks, article_map, multi = {}, [], {}, set()

    for number, story in enumerate(stories, start=1):
        articles = list(
            story.articles.order_by("-published_at")[:MAX_ARTICLES_PER_STORY]
        )
        if not articles:
            results[story.pk] = ValueError("Story has no articles.")
            continue
        article_map[number] = (story, len(articles))
        blocks.append(_story_block(number, story, articles))
        if len(articles) > 1:
            multi.add(number)

    if not blocks:
        return results

    data = generate_json(_build_prompt(blocks, multi))   # may raise
    entries = data.get("stories")
    if not isinstance(entries, list):
        raise ValueError("Gemini response has no 'stories' list.")

    by_number = {}
    for entry in entries:
        try:
            by_number[int(entry.get("story"))] = entry
        except (TypeError, ValueError, AttributeError):
            continue

    for number, (story, article_count) in article_map.items():
        entry = by_number.get(number)
        if entry is None:
            results[story.pk] = ValueError("Gemini omitted this story.")
            continue
        try:
            _validate_and_save(story, entry, article_count)
            results[story.pk] = None
        except Exception as error:
            results[story.pk] = error

    return results


def process_story(story):
    """Single-story convenience wrapper (raises on failure)."""
    error = process_batch([story]).get(story.pk)
    if error:
        raise error
    return {
        "summary": story.summary,
        "why_it_matters": story.why_it_matters,
        "category": story.category,
        "importance_score": story.importance_score,
    }
