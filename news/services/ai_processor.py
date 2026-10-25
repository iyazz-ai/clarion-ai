import json
import os

from google import genai

from news.models import Article


MODEL_NAME = "gemini-3.5-flash"

ALLOWED_CATEGORIES = {
    "Models",
    "Agents",
    "Research",
    "Products",
    "Business",
    "Developer Tools",
    "Safety",
    "Other",
}


def process_article(article):
    """
    Analyze one Article using Gemini and save the result.
    """

    client = genai.Client(
        api_key=os.environ["GEMINI_API_KEY"]
    )

    prompt = f"""
Analyze this AI news article.

Title:
{article.title}

Description:
{article.description}

Return ONLY valid JSON.

Required JSON structure:

{{
    "summary": "A concise 2-3 sentence summary.",
    "why_it_matters": "Explain why this matters to someone following AI.",
    "category": "Models, Agents, Research, Products, Business, Developer Tools, Safety, or Other",
    "importance_score": 0
}}

Rules:

- summary must be concise.
- why_it_matters must explain the significance.
- category must be exactly one of the allowed categories.
- importance_score must be a number from 0 to 100.
"""

    interaction = client.interactions.create(
        model=MODEL_NAME,
        input=prompt,
    )

    raw_output = interaction.output_text.strip()

    try:
        data = json.loads(raw_output)
    except json.JSONDecodeError as error:
        raise ValueError(
            f"Gemini returned invalid JSON: {raw_output}"
        ) from error

    required_fields = {
        "summary",
        "why_it_matters",
        "category",
        "importance_score",
    }

    missing_fields = required_fields - data.keys()

    if missing_fields:
        raise ValueError(
            f"Gemini response is missing fields: {missing_fields}"
        )

    category = data["category"]

    if category not in ALLOWED_CATEGORIES:
        raise ValueError(
            f"Invalid category returned by Gemini: {category}"
        )

    try:
        importance_score = float(
            data["importance_score"]
        )
    except (TypeError, ValueError) as error:
        raise ValueError(
            "Importance score must be a number."
        ) from error

    if not 0 <= importance_score <= 100:
        raise ValueError(
            "Importance score must be between 0 and 100."
        )

    article.summary = data["summary"]
    article.why_it_matters = data["why_it_matters"]
    article.category = category
    article.importance_score = importance_score

    article.save(
        update_fields=[
            "summary",
            "why_it_matters",
            "category",
            "importance_score",
        ]
    )

    return {
        "summary": article.summary,
        "why_it_matters": article.why_it_matters,
        "category": article.category,
        "importance_score": article.importance_score,
    }