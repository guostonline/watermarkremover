import json
from modules.ai_client import AIClient

SYSTEM = (
    "You are an SEO expert specializing in sewing, fashion, and craft content for patternslabco.com, "
    "a store selling PDF sewing patterns. Always respond with valid JSON only — no markdown, no explanation."
)

PROMPT_TEMPLATE = """Seed keyword: "{keyword}"

Generate exactly 15 related long-tail keywords for a sewing patterns blog article.
For each keyword return:
- "keyword": the full long-tail phrase
- "intent": one of "informational" | "commercial" | "navigational"
- "volume": one of "low" | "medium" | "high" (estimated monthly search volume)

Return a JSON array of 15 objects. Example:
[
  {{"keyword": "how to sew an A-line dress for beginners", "intent": "informational", "volume": "medium"}},
  ...
]"""


def get_keyword_suggestions(seed: str, ai: AIClient) -> list[dict]:
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": PROMPT_TEMPLATE.format(keyword=seed)},
    ]
    try:
        result = ai.chat_json(messages, temperature=0.6, max_tokens=1500)
        if isinstance(result, list):
            return result[:15]
        return []
    except Exception as e:
        return [{"keyword": seed, "intent": "informational", "volume": "medium", "error": str(e)}]
