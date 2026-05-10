"""Targeted regeneration for failing SEO checks — yields SSE-style dicts for streaming."""
import re
from modules.ai_client import AIClient


def _ai(prompt: str, ai: AIClient, max_tokens: int = 700) -> str:
    return ai.chat(
        [{"role": "user", "content": prompt}],
        temperature=0.5,
        max_tokens=max_tokens,
    ).strip().strip('"\'')


# ── Individual fix functions ──────────────────────────────────

def fix_title(keyword: str, current: str, ai: AIClient) -> str:
    result = _ai(
        f"Write an SEO blog title for keyword: \"{keyword}\"\n"
        f"Rules: 50–60 characters, include the keyword, compelling.\n"
        f"Current title for reference: {current}\n"
        f"Return ONLY the new title text.",
        ai, max_tokens=120,
    )
    return result[:60] if len(result) > 60 else result


def fix_meta(keyword: str, current: str, title: str, ai: AIClient) -> str:
    result = _ai(
        f"Write a meta description for this sewing blog article.\n"
        f"Keyword: \"{keyword}\"\n"
        f"Title: {title}\n"
        f"Rules: EXACTLY 150–160 characters, include keyword, end with a call to action.\n"
        f"Current meta for reference: {current}\n"
        f"Return ONLY the meta description text.",
        ai, max_tokens=200,
    )
    if len(result) > 160:
        result = result[:157] + "..."
    return result


def fix_density(keyword: str, sections: list, ai: AIClient) -> list:
    updated = list(sections)
    # Pick the 2 longest sections
    targets = sorted(
        range(len(updated)),
        key=lambda i: len(updated[i].get("body") or ""),
        reverse=True,
    )[:2]
    for idx in targets:
        body = updated[idx].get("body") or ""
        if len(body.split()) < 20:
            continue
        new_body = _ai(
            f"Rewrite this paragraph to naturally include the phrase \"{keyword}\" once or twice more. "
            f"Keep the meaning and structure the same — just weave the keyword in naturally.\n\n"
            f"Paragraph:\n{body}\n\n"
            f"Return the rewritten paragraph only.",
            ai, max_tokens=800,
        )
        if new_body:
            updated[idx] = {**updated[idx], "body": new_body}
    return updated


def fix_links(sections: list, site_context: list, ai: AIClient) -> list:
    products = [c for c in site_context if c.get("type") == "product"][:15]
    if not products:
        return sections

    product_list = "\n".join(f"- [{p['title']}]({p['url']})" for p in products)
    updated = list(sections)

    def total_links():
        return sum(
            len(re.findall(r'patternslabco\.com', s.get("body") or ""))
            for s in updated
        )

    # Try every section from largest to smallest until we reach 3 links
    order = sorted(range(len(updated)), key=lambda i: len(updated[i].get("body") or ""), reverse=True)

    for idx in order:
        if total_links() >= 3:
            break
        body = updated[idx].get("body") or ""
        if len(body.split()) < 25:
            continue
        new_body = _ai(
            f"Add ONE internal product link into this paragraph using markdown [anchor text](url).\n"
            f"Choose the most relevant product from the list.\n\n"
            f"Paragraph:\n{body}\n\n"
            f"Products:\n{product_list}\n\n"
            f"Return the complete paragraph with the link added.",
            ai, max_tokens=800,
        )
        if new_body and len(new_body) >= len(body) // 2:
            updated[idx] = {**updated[idx], "body": new_body}

    return updated


def fix_direct(keyword: str, sections: list, ai: AIClient) -> list:
    updated = list(sections)
    for i, s in enumerate(updated):
        body = s.get("body") or ""
        if len(body.split()) < 25:
            continue
        new_body = _ai(
            f"Rewrite this paragraph so the very first sentence is a direct answer "
            f'(e.g. starts with "Yes,", "The best way to...", "To sew...", "For a perfect...").\n'
            f"Keep the rest of the paragraph unchanged.\n\n"
            f"Paragraph:\n{body}\n\n"
            f"Return the complete rewritten paragraph.",
            ai, max_tokens=800,
        )
        if new_body:
            updated[i] = {**updated[i], "body": new_body}
        break
    return updated


# ── Main streaming optimizer ──────────────────────────────────

def optimize_stream(article: dict, keyword: str, failed_ids: list, site_context: list, ai: AIClient):
    """Generator — yields dicts for SSE. Caller wraps in json.dumps."""
    result = dict(article)
    sections = list(result.get("sections") or [])

    STEPS = [
        ("title_length",  "Regenerating SEO title..."),
        ("meta_length",   "Regenerating meta description..."),
        ("kw_density",    "Improving keyword density..."),
        ("internal_links","Adding internal product links..."),
        ("direct_answer", "Adding direct answer paragraph..."),
    ]

    applied = []

    for check_id, label in STEPS:
        if check_id not in failed_ids:
            continue

        yield {"type": "progress", "message": label}

        try:
            if check_id == "title_length":
                result["seo_title"] = fix_title(keyword, result.get("seo_title") or "", ai)
                applied.append("Title")

            elif check_id == "meta_length":
                result["meta_description"] = fix_meta(
                    keyword,
                    result.get("meta_description") or "",
                    result.get("seo_title") or "",
                    ai,
                )
                applied.append("Meta description")

            elif check_id == "kw_density":
                sections = fix_density(keyword, sections, ai)
                applied.append("Keyword density")

            elif check_id == "internal_links":
                sections = fix_links(sections, site_context, ai)
                applied.append("Internal links")

            elif check_id == "direct_answer":
                sections = fix_direct(keyword, sections, ai)
                applied.append("Direct answer")

            yield {"type": "step_done", "check_id": check_id}

        except Exception as e:
            yield {"type": "step_error", "check_id": check_id, "error": str(e)}

    result["sections"] = sections
    yield {"type": "done", "article": result, "applied": applied}
