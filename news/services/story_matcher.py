"""
Decides whether two articles describe the SAME EVENT.

Why the old matcher failed
--------------------------
* token_set_ratio returns 100 when one title's words are a subset of the
  other's, so short titles matched almost anything.
* A shared *generic* entity ("OpenAI") counted as 100% entity overlap.
* All weights were added into one score, so several weak signals (same
  publisher + same week + shared brand) could add up to a "match".
* The `entities__overlap` prefilter does not exist for JSONField on
  Django - it silently became a no-op.

New approach: explicit rules, no adding up of weak signals.
Two articles match only if they are close in time AND one of these holds:

  A. Near-identical wording      (distinctive-word Jaccard high)
  B. Different publishers share a SPECIFIC entity (e.g. gpt-5.1, codex)
  C. Same publisher, share a specific entity, very close in time and
     reasonably similar wording (launch post + developer post)

Articles from the SAME source that only share a generic brand name (the
OpenAI customer-story case) can never match.
"""

import re
from dataclasses import dataclass
from datetime import timedelta

from news.models import Article, Story
from news.services.entity_extractor import (
    BROAD_ENTITIES,
    extract_entities,
    extract_model_entities,
)
from news.services.similarity import (
    COMMON_AI_TERMS,
    TokenRarity,
    distinctive_tokens,
    jaccard,
)

# ---- tunable thresholds -------------------------------------------------
MAX_DAYS_APART = 4            # hard gate for every rule

RULE_A_MIN_JACCARD = 0.60     # near-identical wording, different sources
RULE_A_MIN_SHARED = 2
RULE_A_SAME_SOURCE_JACCARD = 0.85
RULE_A_SAME_SOURCE_SHARED = 3

RULE_B_MAX_DAYS = 3           # shared specific entity, different sources
RULE_B_MIN_JACCARD = 0.20

RULE_C_MAX_DAYS = 2           # shared specific entity, same source
RULE_C_MIN_JACCARD = 0.40

RULE_C2_MAX_DAYS = 1          # same source, SAME MODEL VERSION, same day
RULE_C2_MIN_JACCARD = 0.25

RULE_E_MAX_DAYS = 1.5         # different sources, shared RARE word
RULE_E_MIN_SHARED = 2

RULE_D_MAX_DAYS = 3           # different sources, many shared words
RULE_D_MIN_SHARED = 3
RULE_D_MIN_CONTAINMENT = 0.40  # shared / size of the shorter title
# -------------------------------------------------------------------------


@dataclass
class MatchResult:
    matched: bool
    score: float
    rule: str = ""


NO_MATCH = MatchResult(False, 0.0, "")


# "How Amgen uses GPT-5", "Inside X: how Y built ..." - customer case studies.
# They mention a product but are not the product's news event.
_CUSTOMER_STORY = re.compile(
    r"^(how|inside)\b.*\b(uses|using|is using|built|builds|scales|scaled|"
    r"transforms|accelerates)\b"
    r"|\b(adopts|leverages|integrates|streamlines|scales|powers)\b.*"
    r"\b(chatgpt|codex|gpt-?\d|openai|gemini|claude)\b"
    r"|\b(reviewed|reviews|saves|saved|cuts|reduces|reconciles|automates|"
    r"speeds up|streamlines)\b.*\b(with|using)\b.*"
    r"\b(chatgpt|codex|gpt-?\d|openai|gemini|claude)\b",
    re.IGNORECASE,
)


def is_customer_story(title):
    return bool(_CUSTOMER_STORY.search(title or ""))


def days_apart(date_a, date_b):
    if not date_a or not date_b:
        return None
    return abs((date_a - date_b).total_seconds()) / 86400


def evaluate_pair(a, b, rarity=None):
    """
    a, b: any objects with .title, .source and .published_at.
    rarity: optional TokenRarity built from recent titles (enables Rule E).
    Returns a MatchResult.
    """
    gap = days_apart(a.published_at, b.published_at)

    # Unknown dates -> we cannot verify the time gate, so never merge.
    if gap is None or gap > MAX_DAYS_APART:
        return NO_MATCH

    tokens_a = distinctive_tokens(a.title)
    tokens_b = distinctive_tokens(b.title)
    if not tokens_a or not tokens_b:
        return NO_MATCH

    shared_tokens = tokens_a & tokens_b
    sim = jaccard(tokens_a, tokens_b)
    shared_entities = (
        extract_entities(a.title) & extract_entities(b.title)
    ) - BROAD_ENTITIES
    same_source = (a.source or "").lower() == (b.source or "").lower()

    # A customer case study and a product announcement are different events.
    if is_customer_story(a.title) != is_customer_story(b.title):
        return NO_MATCH

    # Rule 0 - identical distinctive words (re-posts / renamed duplicates)
    if tokens_a == tokens_b:
        return MatchResult(True, 100.0, "0:identical")

    # Two customer case studies ("How Amgen uses GPT-5" / "How AstraZeneca
    # uses GPT-5") are different events even when the wording is similar and
    # even across publishers, so they get the strict (same-source) threshold
    # and may never use the entity / overlap rules below.
    both_customer = is_customer_story(a.title) and is_customer_story(b.title)

    # Rule A - near-identical wording
    if same_source or both_customer:
        if (sim >= RULE_A_SAME_SOURCE_JACCARD
                and len(shared_tokens) >= RULE_A_SAME_SOURCE_SHARED):
            return MatchResult(True, sim * 100, "A:strict-wording")
    else:
        if (sim >= RULE_A_MIN_JACCARD
                and len(shared_tokens) >= RULE_A_MIN_SHARED):
            return MatchResult(True, sim * 100, "A:wording")

    if both_customer:
        return NO_MATCH

    # Rule D - independent publishers, same story told in different words
    if not same_source and gap <= RULE_D_MAX_DAYS:
        containment = len(shared_tokens) / min(len(tokens_a), len(tokens_b))
        meaningful = shared_tokens - COMMON_AI_TERMS
        if (len(meaningful) >= RULE_D_MIN_SHARED
                and containment >= RULE_D_MIN_CONTAINMENT):
            return MatchResult(True, 50 + containment * 40, "D:overlap")

    # Rule B - independent publishers covering the same specific thing
    if (not same_source and shared_entities
            and gap <= RULE_B_MAX_DAYS and sim >= RULE_B_MIN_JACCARD):
        return MatchResult(
            True, 60 + sim * 40 + 5 * len(shared_entities), "B:entity"
        )

    # Rule C - same publisher, same specific thing, same day or so
    if (same_source and shared_entities
            and gap <= RULE_C_MAX_DAYS and sim >= RULE_C_MIN_JACCARD):
        return MatchResult(
            True, 50 + sim * 40 + 5 * len(shared_entities), "C:same-source-entity"
        )

    # Rule C2 - same publisher, SAME VERSIONED MODEL ("Gemini 4 Argon for
    # Robotics" / "Developing Gemini 4 Argon responsibly"): a launch is
    # usually announced as several posts on the same day.
    shared_models = extract_model_entities(a.title) & extract_model_entities(b.title)
    if (same_source and shared_models
            and gap <= RULE_C2_MAX_DAYS and sim >= RULE_C2_MIN_JACCARD):
        return MatchResult(True, 50 + sim * 40 + 5 * len(shared_models), "C2:model-version")

    # Rule E - different publishers, same day, at least two shared words and
    # at least one of them RARE across recent titles ("bluesky", "attie").
    # Needs a big enough corpus to judge rarity, otherwise it stays off.
    if rarity is not None and rarity.reliable and not same_source \
            and gap <= RULE_E_MAX_DAYS:
        meaningful = shared_tokens - COMMON_AI_TERMS
        # a rare word must also be a real word-like token (not 'ai', 'ceo')
        rare_shared = {t for t in meaningful if len(t) >= 5 and rarity.is_rare(t)}
        if len(meaningful) >= RULE_E_MIN_SHARED and rare_shared:
            return MatchResult(True, 55 + 5 * len(rare_shared), "E:rare-words")

    return NO_MATCH


def best_group_match(article, members, rarity=None):
    """
    Does `article` belong in a group with these `members`?

    The old rule ("matches ANY member") allowed chains: A~B and B~C put A and
    C in one story even when A and C are different events. Now an article
    must match a MAJORITY of the members it can be compared with (those
    within MAX_DAYS_APART), so one weak link is not enough.

        1 comparable member  -> must match it
        2 comparable members -> must match both
        3 -> 2 of 3,  4 -> 3 of 4, ...

    Returns a MatchResult (score = best pairwise score).
    """
    comparable = []
    for member in members:
        if member.pk is not None and member.pk == article.pk:
            continue
        gap = days_apart(article.published_at, member.published_at)
        if gap is not None and gap <= MAX_DAYS_APART:
            comparable.append(member)

    if not comparable:
        return NO_MATCH

    results = [evaluate_pair(article, m, rarity) for m in comparable]
    matched = [r for r in results if r.matched]
    needed = len(comparable) // 2 + 1

    if len(matched) < needed:
        return NO_MATCH
    return max(matched, key=lambda r: r.score)


def group_articles(articles, rarity=None):
    """
    Pure in-memory clustering (no DB writes). Articles are processed in
    (published_at, id) order so the result is deterministic for a given set
    of articles. Used by `regroup_stories` and the tests.
    Undated articles are never grouped (they are skipped here).
    """
    ordered = sorted(
        (a for a in articles if a.published_at),
        key=lambda a: (a.published_at, a.pk or 0),
    )
    if rarity is None:
        rarity = TokenRarity(a.title for a in ordered)
    groups = []
    for article in ordered:
        best_group, best_score = None, 0.0
        for group in groups:
            result = best_group_match(article, group, rarity)
            if result.matched and result.score > best_score:
                best_group, best_score = group, result.score
        if best_group is None:
            groups.append([article])
        else:
            best_group.append(article)
    return groups


def find_matching_story(article):
    """Find the existing Story this article belongs to, if any."""
    if not article.published_at:
        return None, 0.0

    window = timedelta(days=MAX_DAYS_APART)
    corpus = Article.objects.filter(
        published_at__gte=article.published_at - timedelta(days=30),
        published_at__lte=article.published_at + timedelta(days=1),
    ).values_list("title", flat=True)
    rarity = TokenRarity(corpus)
    candidates = (
        Story.objects
        .filter(articles__published_at__range=(
            article.published_at - window,
            article.published_at + window,
        ))
        .distinct()
        .prefetch_related("articles")
    )

    best_story, best_score = None, 0.0
    for story in candidates:
        result = best_group_match(article, list(story.articles.all()), rarity)
        if result.matched and result.score > best_score:
            best_story, best_score = story, result.score

    if best_story:
        return best_story, best_score
    return None, 0.0
