import json
import re
from modules.ai_client import AIClient
from modules.image_config import SITE_STYLE, COVER_SIZE, INPOST_SIZE

ARTICLE_SCHEMA = {
    "seo_title": "string (50-60 chars, includes primary keyword AND a specific number e.g. '10 Best...', '7 Tips...')",
    "meta_description": "string (150-160 chars)",
    "slug": "string (URL-friendly slug)",
    "cover_image_prompt": f"Midjourney/DALL-E prompt for the featured/cover image ({COVER_SIZE}px landscape)",
    "sections": [
        {
            "heading": "H2 or H3 text (empty string for intro section)",
            "heading_level": "h2 or h3",
            "body": (
                "Short paragraphs ONLY — max 3 sentences per paragraph, separated by \\n\\n. "
                "Embed internal links as [anchor text](https://patternslabco.com/...) "
                "AND outbound links as [anchor text](https://external-source.com/...) to cite research sources."
            ),
            "image_prompt": f"Midjourney/DALL-E prompt for this section ({INPOST_SIZE}px)",
            "sources": ["FULL URL of source cited in this section, e.g. https://example.com/page"]
        }
    ],
    "faq": [
        {"question": "FAQ question", "answer": "Detailed answer (2-3 sentences)"}
    ],
    "schema_type": "Article | HowTo | FAQPage"
}

SYSTEM = (
    "You are a professional SEO content writer specializing in sewing, patterns, and fashion crafts. "
    "You write for patternslabco.com which sells PDF sewing patterns. "
    "Always respond with valid JSON only — no markdown fences, no explanation outside the JSON."
)

ARTICLE_PROMPT = """Write a complete SEO-optimized blog article. Return ONLY valid JSON.

PRIMARY KEYWORD: {keyword}
RELATED KEYWORDS TO INCLUDE: {related_keywords}

INTERNAL LINKS — use EXACTLY these URLs in 3–5 body links (format: [anchor text](https://patternslabco.com/...)):
PRODUCTS:
{product_links}

BLOG POSTS:
{post_links}

WEB RESEARCH (use FULL URLs for outbound links):
{research_text}

IMAGE STYLE for ALL image_prompt fields:
{image_style}

IMAGE SIZES:
- cover_image_prompt: {cover_size}px landscape
- section image_prompt: {inpost_size}px

═══════════════════════════════════════════
MANDATORY SEO RULES — ALL MUST PASS
═══════════════════════════════════════════

RULE 1 — SEO TITLE (50–60 characters EXACTLY, count every character):
  ✓ Must include primary keyword
  ✓ Must include a number (7, 10, 12, etc.)
  ✓ Count: "10 Best Sewing Tips for Beginners 2026" = 39 chars (too short)
  ✓ Good example: "10 Essential Sewing Tips Every Beginner Needs in 2026" = 53 chars
  ✗ Do NOT submit a title shorter than 50 or longer than 60 characters.

RULE 2 — KEYWORD DENSITY (must be 1–3%):
  ✓ Use the exact phrase "{keyword}" at least 12 times across all section bodies.
  ✓ Vary naturally: use it in headings, first sentence of sections, and mid-paragraph.
  ✗ Do NOT use it fewer than 10 times — that gives <1% density and fails.

RULE 3 — INTERNAL LINKS (3–5 links to patternslabco.com REQUIRED):
  ✓ Embed exactly like this: [anchor text](https://patternslabco.com/product-page)
  ✓ Use URLs from the PRODUCTS and BLOG POSTS lists above.
  ✓ Spread across different sections — not all in one place.
  ✗ URLs must start with https://patternslabco.com — no other domain counts.

RULE 4 — DIRECT ANSWER OPENING (intro section body MUST start with one of these):
  ✓ "The best {keyword} ..."
  ✓ "Yes, {keyword} ..."
  ✓ "The key to {keyword} ..."
  ✓ "To master {keyword}, ..."
  ✗ Do NOT start the intro with "Are you...", "In today's...", "Sewing is...", or any other phrase.

RULE 5 — BULLETED OR NUMBERED LIST (at least one REQUIRED):
  ✓ Use markdown format with a blank line before and after:

  - First item
  - Second item
  - Third item

  ✓ Or numbered: 1. First  2. Second  3. Third
  ✗ Writing "First... Second... Third..." in a paragraph does NOT count as a list.

RULE 6 — E-E-A-T EXPERTISE SIGNALS (at least one REQUIRED):
  ✓ You MUST use at least one of these EXACT phrases somewhere in the article body:
    → "In our experience"
    → "We recommend"
    → "our patterns"
    → "years of sewing"
    → "professional sewist"
    → "pattern designer"
  ✗ Paraphrasing these does NOT count — use the exact phrase.

RULE 7 — OUTBOUND LINKS (3+ external links REQUIRED):
  ✓ Embed research source URLs directly in sentences: "According to [Site](https://full-url.com), ..."
  ✗ Listing URLs only in the sources array does NOT count.

RULE 8 — SHORT PARAGRAPHS:
  ✓ Max 3 sentences per paragraph. Separate with blank line (\\n\\n).

OTHER REQUIREMENTS:
- MINIMUM 1000 words total body text
- Each H2 section body: AT LEAST 120 words
- Structure: 1 intro (empty heading) + 6–8 H2 sections + 1 conclusion
- FAQ: 4–5 questions
- Meta description: 150–160 characters
- schema_type: Article, HowTo, or FAQPage

═══════════════════════════════════════════
BEFORE RETURNING, VERIFY:
□ Title is between 50 and 60 characters (count manually)
□ Keyword "{keyword}" appears at least 12 times in body text
□ 3–5 links starting with https://patternslabco.com are embedded
□ Intro body starts with "The best", "Yes,", "The key", or "To master"
□ At least one markdown list (- item or 1. item) exists
□ At least one E-E-A-T phrase from Rule 6 is present
═══════════════════════════════════════════

Return JSON matching this exact schema:
{schema}"""


def _format_links(items: list[dict], link_type: str) -> str:
    filtered = [i for i in items if i.get("type") == link_type][:20]
    if not filtered:
        return "None available"
    return "\n".join(f"- [{i['title']}]({i['url']})" for i in filtered)


def _format_research(research: list[dict]) -> str:
    if not research:
        return "No web research available — write from expertise."
    parts = []
    for r in research:
        parts.append(f"Source URL: {r['url']}\nDomain: {r['domain']}\n{r['text'][:1500]}")
    return "\n\n---\n\n".join(parts)


def _count_words(article: dict) -> int:
    parts = []
    for s in article.get("sections", []) or []:
        parts.append(s.get("body") or "")
        parts.append(s.get("heading") or "")
    for f in article.get("faq", []) or []:
        parts.append(f.get("question") or "")
        parts.append(f.get("answer") or "")
    return len(" ".join(parts).split())


def _auto_fix_seo(article: dict, keyword: str, site_context: list[dict]) -> dict:
    """Programmatically patch common SEO failures that the AI still misses."""
    import re

    # ── 1. Title length: trim if > 60, warn if < 50 ──────────────────────────
    title = article.get("seo_title", "")
    if len(title) > 60:
        article["seo_title"] = title[:57].rstrip() + "..."

    # ── 2. Direct answer: intro body must start with trigger phrase ───────────
    trigger = re.compile(
        r'^(Yes,|No,|The (best|key|answer|secret)|To (sew|make|create|master))',
        re.IGNORECASE
    )
    has_direct = any(
        trigger.match((s.get("body") or "").strip())
        for s in article.get("sections", []) or []
    )
    if not has_direct:
        for s in article.get("sections", []) or []:
            if not s.get("heading"):  # intro section
                s["body"] = (
                    f"The best {keyword} results come from combining the right technique "
                    f"with quality materials and consistent practice.\n\n"
                    + (s.get("body") or "")
                )
                break

    # ── 3. Bulleted list: inject into first section that lacks one ────────────
    has_list = any(
        re.search(r'^\s*[-*\d+]\s', s.get("body") or "", re.MULTILINE)
        for s in article.get("sections", []) or []
    )
    if not has_list:
        for s in article.get("sections", []) or []:
            if s.get("heading") and len((s.get("body") or "").split()) > 80:
                paras = (s.get("body") or "").split("\n\n")
                list_block = (
                    "\n\nHere are the key things to keep in mind:\n\n"
                    f"- Choose the right fabric weight for {keyword}\n"
                    "- Follow pattern instructions step by step\n"
                    "- Press seams as you go for a professional finish\n"
                    "- Measure twice before cutting\n"
                )
                if len(paras) >= 2:
                    paras.insert(1, list_block)
                else:
                    paras.append(list_block)
                s["body"] = "\n\n".join(paras)
                break

    # ── 4. E-E-A-T: inject a phrase if none of the signals are present ────────
    eeat_signals = [
        "in our experience", "when testing", "we recommend",
        "our patterns", "years of sewing", "professional sewist", "pattern designer"
    ]
    full_text = " ".join(
        (s.get("body") or "") for s in article.get("sections", []) or []
    ).lower()
    if not any(sig in full_text for sig in eeat_signals):
        # Append to the last substantial section
        for s in reversed(article.get("sections", []) or []):
            if len((s.get("body") or "").split()) > 60:
                s["body"] = (s.get("body") or "").rstrip() + (
                    f"\n\nIn our experience working with sewists of all levels, we recommend "
                    f"starting with our patterns at patternslabco.com — they include "
                    f"step-by-step guidance that makes {keyword} approachable for everyone."
                )
                break

    # ── 5. Internal links: inject if fewer than 3 patternslabco.com links ─────
    all_body = " ".join(s.get("body") or "" for s in article.get("sections", []) or [])
    link_count = len(re.findall(r'\[.+?\]\(https?://patternslabco\.com[^)]*\)', all_body))
    if link_count < 3:
        products = [i for i in site_context if i.get("type") == "product" and i.get("url") and i.get("title")][:5]
        needed = 3 - link_count
        injected = 0
        for s in article.get("sections", []) or []:
            if injected >= needed:
                break
            body = s.get("body") or ""
            if not s.get("heading") or len(body.split()) < 60:
                continue
            if injected < len(products):
                p = products[injected]
                link = f' — explore our [**{p["title"]}**]({p["url"]}) pattern for a perfect result'
                paras = body.split("\n\n")
                paras[0] = paras[0].rstrip(".") + link + "."
                s["body"] = "\n\n".join(paras)
                injected += 1

    return article


def _enrich_image_prompts(article: dict) -> dict:
    """Ensure every image prompt contains the site style and correct size."""
    style_suffix = f" | {SITE_STYLE} | no text overlays, no watermarks"

    # Cover
    cover = article.get("cover_image_prompt") or ""
    if SITE_STYLE[:30] not in cover:
        article["cover_image_prompt"] = f"{cover}{style_suffix} | {COVER_SIZE}px horizontal"

    # Sections
    for s in article.get("sections", []) or []:
        prompt = s.get("image_prompt") or ""
        if SITE_STYLE[:30] not in prompt:
            s["image_prompt"] = f"{prompt}{style_suffix} | {INPOST_SIZE}px horizontal"

    return article


def generate_article(
    keyword: str,
    selected_keywords: list[str],
    research: list[dict],
    site_context: list[dict],
    ai: AIClient,
) -> dict:
    related = ", ".join(selected_keywords[:10]) if selected_keywords else keyword
    product_links = _format_links(site_context, "product")
    post_links = _format_links(site_context, "post")
    research_text = _format_research(research)

    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": ARTICLE_PROMPT.format(
            keyword=keyword,
            related_keywords=related,
            product_links=product_links,
            post_links=post_links,
            research_text=research_text,
            image_style=SITE_STYLE,
            cover_size=COVER_SIZE,
            inpost_size=INPOST_SIZE,
            schema=json.dumps(ARTICLE_SCHEMA, indent=2),
        )},
    ]
    article = ai.chat_json(messages, temperature=0.7, max_tokens=8000)
    article["word_count"] = _count_words(article)
    article["sources"] = [r["url"] for r in research]

    # ── Enforce 1000-word minimum ──────────────────────────
    if article["word_count"] < 1000:
        thin_sections = [
            {"index": i, "heading": s.get("heading", ""), "body": s.get("body", ""), "words": len((s.get("body") or "").split())}
            for i, s in enumerate(article.get("sections", []))
            if len((s.get("body") or "").split()) < 120
        ]
        expand_prompt = f"""The article below is only {article["word_count"]} words — it MUST reach at least 1000 words.

KEYWORD: {keyword}

Expand EACH of these thin sections to at least 150 words each. Return ONLY a JSON array of the expanded sections in this format:
[{{"index": 0, "body": "expanded text..."}}]

THIN SECTIONS TO EXPAND:
{json.dumps(thin_sections, indent=2)}"""

        expansion = ai.chat_json(
            [{"role": "system", "content": SYSTEM}, {"role": "user", "content": expand_prompt}],
            temperature=0.7,
            max_tokens=4000,
        )
        if isinstance(expansion, list):
            for item in expansion:
                idx = item.get("index")
                body = item.get("body", "")
                if idx is not None and 0 <= idx < len(article.get("sections", [])):
                    article["sections"][idx]["body"] = body
        elif isinstance(expansion, dict) and "sections" in expansion:
            for item in expansion["sections"]:
                idx = item.get("index")
                body = item.get("body", "")
                if idx is not None and 0 <= idx < len(article.get("sections", [])):
                    article["sections"][idx]["body"] = body
        article["word_count"] = _count_words(article)
    # ──────────────────────────────────────────────────────

    article = _auto_fix_seo(article, keyword, site_context)
    article["word_count"] = _count_words(article)
    article = _enrich_image_prompts(article)
    return article


REGEN_PROMPT = """Rewrite ONLY this one section. Return ONLY valid JSON for the single section.

ARTICLE TOPIC: {keyword}
HEADING: {heading}
CURRENT BODY: {body}

ADJACENT SECTIONS: prev="{prev_heading}" | next="{next_heading}"
AVAILABLE INTERNAL LINKS: {link_options}

IMAGE STYLE TO USE: {image_style}
IMAGE SIZE: {inpost_size}px horizontal

Requirements:
- Keep or slightly improve the heading
- 150–300 words, fresh angle
- SHORT PARAGRAPHS: max 2-3 sentences per paragraph, separated by blank lines
- Embed at least 1 outbound link to an external source if research is available
- Updated image_prompt with style and size
- sources: list full URLs only if you cite from provided research

Return JSON:
{{"heading": "...", "heading_level": "h2", "body": "...", "image_prompt": "...", "sources": []}}"""


def regenerate_section(
    keyword: str,
    section: dict,
    prev_heading: str,
    next_heading: str,
    site_context: list[dict],
    ai: AIClient,
) -> dict:
    links = [i for i in site_context if i.get("type") == "product"][:10]
    link_options = ", ".join(f"[{i['title']}]({i['url']})" for i in links) or "None"

    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": REGEN_PROMPT.format(
            keyword=keyword,
            heading=section.get("heading") or "",
            body=section.get("body") or "",
            prev_heading=prev_heading or "Introduction",
            next_heading=next_heading or "Conclusion",
            link_options=link_options,
            image_style=SITE_STYLE,
            inpost_size=INPOST_SIZE,
        )},
    ]
    result = ai.chat_json(messages, temperature=0.8, max_tokens=800)
    # Ensure style is present
    prompt = result.get("image_prompt") or ""
    if SITE_STYLE[:30] not in prompt:
        result["image_prompt"] = f"{prompt} | {SITE_STYLE} | {INPOST_SIZE}px"
    return result
