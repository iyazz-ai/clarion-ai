"""
Entity extraction for article titles.

Two kinds of entities, and the difference is the whole point:

* GENERIC_ORGS  - publishers / big labs (OpenAI, Google, ...). Hundreds of
  unrelated articles mention them, so sharing one is NOT evidence that two
  articles describe the same event. They are ignored for matching.
* SPECIFIC entities - model versions (gpt-5.1), products, techniques
  (codex, alphagenome, lora). Sharing one IS meaningful evidence.

Matching uses word boundaries, so "recognition" no longer matches
"cognition" and "Colorado" no longer matches "lora".
"""

import re

GENERIC_ORGS = {
    "openai", "anthropic", "google", "deepmind", "hugging", "face",
    "microsoft", "meta", "nvidia", "amazon", "aws", "apple", "xai",
}

# Products / techniques / companies that identify a specific topic.
# Add new ones here as you see them in your feed.
SPECIFIC_ENTITIES = {
    "perplexity", "cognition", "devin", "playco", "legora", "chatgpt",
    "codex", "gradio", "automatic1111", "alphagenome", "grpo", "lora",
    "nccl", "fyxer", "sora",
}

# Product umbrellas with dozens of unrelated posts ("ChatGPT for sales teams",
# "ChatGPT for finance teams"). Kept as entities, but sharing one is NOT
# enough evidence that two articles are the same event.
BROAD_ENTITIES = {"chatgpt", "codex"}

_ENTITY_PATTERNS = {
    entity: re.compile(rf"(?<![a-z0-9]){re.escape(entity)}(?![a-z0-9])")
    for entity in SPECIFIC_ENTITIES
}

# Matches "GPT-5", "GPT 5.1", "Gemini 2.5", "Claude 4", "GPT-4o"...
# It deliberately does NOT swallow the following word, so
# "GPT-5 is now available" -> "gpt-5" (the old code produced "gpt-5 is").
MODEL_PATTERN = re.compile(
    r"\b(gpt|gemini|claude|llama|gemma|qwen|deepseek|grok|mistral)"
    r"[\s\-]*(\d+(?:\.\d+)?[a-z]?)\b",
    flags=re.IGNORECASE,
)


def extract_entities(title):
    """Return the set of SPECIFIC entities found in a title."""
    if not title:
        return set()

    entities = set()
    title_lower = title.lower()

    for family, version in MODEL_PATTERN.findall(title_lower):
        entities.add(f"{family}-{version}")

    for entity, pattern in _ENTITY_PATTERNS.items():
        if pattern.search(title_lower):
            entities.add(entity)

    return entities


def extract_model_entities(title):
    """Only versioned model names ("gemini-4", "gpt-5.1"). A new model version
    is a strong, specific signal that two posts are about the same release."""
    if not title:
        return set()
    return {
        f"{family}-{version}"
        for family, version in MODEL_PATTERN.findall(title.lower())
    }
