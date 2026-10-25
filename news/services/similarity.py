"""Title normalisation and similarity helpers."""

import re

from rapidfuzz.fuzz import token_sort_ratio

from news.services.entity_extractor import GENERIC_ORGS

# Words that appear in thousands of headlines and say nothing about *which*
# event this is. Tune this list as you see false matches.
BOILERPLATE = {
    "the", "a", "an", "and", "or", "for", "with", "to", "in", "of", "on",
    "is", "are", "was", "be", "by", "at", "as", "from", "that", "this",
    "it", "its", "into", "your", "our", "we", "you", "can", "will", "now",
    "new", "introducing", "introduces", "announcing", "announces", "how",
    "why", "what", "next", "generation", "helps", "help", "helping",
    "uses", "use", "using", "used", "builds", "build", "building",
    "scaling", "scales", "scale", "powers", "powering", "power",
    "transforms", "transform", "transforming", "accelerates",
    "accelerate", "improves", "improve", "enables", "enable",
    "test", "testing", "work", "own", "people", "systems", "services",
    "ai", "more", "using", "via", "after", "about", "has", "have",
    "case", "study", "customer", "story",
    "system", "card", "overview", "here", "learn",
    # everyday words that say nothing about WHICH event this is
    "less", "time", "like", "don", "says", "say", "said", "ceo", "may",
    "could", "would", "should", "think", "last", "get", "gets", "make",
    "makes", "just", "still", "also", "even", "many", "most", "much",
    "than", "then", "over", "under", "out", "off", "up", "down", "all",
    "any", "some", "every", "one", "two", "first", "why",
}

# Descriptive AI vocabulary. Many unrelated articles share these words, so
# they do not count as evidence for the "different sources, similar words" rule.
COMMON_AI_TERMS = {
    "model", "open", "multimodal", "lightweight", "agent", "language",
    "learning", "large", "small", "fast", "faster", "better", "smarter",
    "release", "launch", "launches", "update", "tool", "platform",
    "research", "data", "center", "startup", "company", "report",
}

_TOKEN_RE = re.compile(r"[a-z0-9]+(?:[.\-][a-z0-9]+)*")


def _light_stem(token):
    if len(token) > 4 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def distinctive_tokens(title):
    """
    Tokens that actually identify the event: lowercase, no boilerplate,
    no generic publisher names ("openai", "google", ...).
    """
    if not title:
        return set()

    tokens = set()
    for raw in _TOKEN_RE.findall(title.lower().replace("\u2019s", "")):
        if raw in BOILERPLATE or raw in GENERIC_ORGS:
            continue
        if len(raw) == 1 and raw.isalpha():      # "t" and "s" from don't / it's
            continue
        tokens.add(_light_stem(raw))
    return tokens


def jaccard(tokens_a, tokens_b):
    if not tokens_a or not tokens_b:
        return 0.0
    return len(tokens_a & tokens_b) / len(tokens_a | tokens_b)


def calculate_title_similarity(title1, title2):
    """
    0-100 similarity of two titles after removing boilerplate and publisher
    names. Uses token_sort_ratio (NOT token_set_ratio, which returns 100
    whenever one title's words are a subset of the other's).
    """
    a = " ".join(sorted(distinctive_tokens(title1)))
    b = " ".join(sorted(distinctive_tokens(title2)))
    if not a or not b:
        return 0
    return token_sort_ratio(a, b)


class TokenRarity:
    """
    How common is a word across recent titles? A word shared by two articles
    is only strong evidence when it is RARE ("bluesky", "attie"), not when
    it is everywhere ("safety", "ceo"). Built from a list of titles.

    Only trustworthy with a reasonably large corpus, so `reliable` is False
    for small ones and rarity-based rules stay switched off.
    """

    MIN_CORPUS = 100

    def __init__(self, titles):
        titles = list(titles)
        self.n = len(titles)
        self.df = {}
        for title in titles:
            for token in distinctive_tokens(title):
                self.df[token] = self.df.get(token, 0) + 1
        self.max_df = max(3, int(0.002 * self.n))

    @property
    def reliable(self):
        return self.n >= self.MIN_CORPUS

    def is_rare(self, token):
        return self.df.get(token, 0) <= self.max_df
