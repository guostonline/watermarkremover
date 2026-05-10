import re


def _full_text(article: dict) -> str:
    parts = [article.get("seo_title") or "", article.get("meta_description") or ""]
    for s in article.get("sections", []) or []:
        parts.append(s.get("heading") or "")
        parts.append(s.get("body") or "")
    for f in article.get("faq", []) or []:
        parts.append(f.get("question") or "")
        parts.append(f.get("answer") or "")
    return " ".join(parts)


def _word_count(text: str) -> int:
    return len(text.split())


def _keyword_density(text: str, keyword: str) -> float:
    words = text.lower().split()
    if not words:
        return 0.0
    kw_words = keyword.lower().split()
    count = sum(1 for i in range(len(words) - len(kw_words) + 1)
                if words[i:i + len(kw_words)] == kw_words)
    return round(count / len(words) * 100, 2)


def _count_internal_links(article: dict) -> int:
    count = 0
    for s in article.get("sections", []) or []:
        count += len(re.findall(r'\[.+?\]\(https?://patternslabco\.com[^)]*\)', s.get("body") or ""))
    return count


def _count_outbound_links(article: dict) -> int:
    count = 0
    for s in article.get("sections", []) or []:
        body = s.get("body") or ""
        all_links = re.findall(r'\[.+?\]\((https?://[^)]+)\)', body)
        count += sum(1 for url in all_links if "patternslabco.com" not in url)
    return count


def _title_has_number(title: str) -> bool:
    return bool(re.search(r'\d', title))


def _has_long_paragraph(article: dict, max_sentences: int = 4) -> bool:
    """Returns True if any paragraph exceeds max_sentences (RankMath flags these)."""
    sentence_end = re.compile(r'[.!?][\s"\')\]]*(?=[A-Z\s]|$)')
    for s in article.get("sections", []) or []:
        body = s.get("body") or ""
        for para in re.split(r'\n\n+', body):
            para = para.strip()
            if not para:
                continue
            sentences = [p for p in sentence_end.split(para) if p.strip()]
            if len(sentences) > max_sentences:
                return True
    return False


def _avg_sentence_length(text: str) -> float:
    sentences = re.split(r'[.!?]+', text)
    sentences = [s.strip() for s in sentences if s.strip()]
    if not sentences:
        return 0.0
    return sum(len(s.split()) for s in sentences) / len(sentences)


def _has_list(article: dict) -> bool:
    for s in article.get("sections", []) or []:
        body = s.get("body") or ""
        if re.search(r'^\s*[\-\*\d]\s', body, re.MULTILINE):
            return True
    return False


def _has_direct_answer(article: dict) -> bool:
    for s in article.get("sections", []) or []:
        body = (s.get("body") or "").strip()
        if re.match(r'^(Yes,|No,|The (best|answer|key|secret)|To (sew|make|create))', body, re.IGNORECASE):
            return True
    return False


def _has_eeat(article: dict) -> bool:
    combined = _full_text(article).lower()
    signals = ["in our experience", "when testing", "we recommend", "our patterns",
               "years of sewing", "professional sewist", "pattern designer"]
    return any(s in combined for s in signals)


def check_seo(article: dict, keyword: str) -> dict:
    title = article.get("seo_title") or ""
    meta = article.get("meta_description") or ""
    full = _full_text(article)
    wc = article.get("word_count") or _word_count(full)
    density = _keyword_density(full, keyword)
    internal_links = _count_internal_links(article)
    h2_count = sum(1 for s in article.get("sections", []) if s.get("heading_level") == "h2")
    faq_count = len(article.get("faq", []))
    avg_sent = _avg_sentence_length(full)

    # First ~100 words of first section
    first_section_body = ""
    for s in article.get("sections", []):
        if s.get("body"):
            first_section_body = " ".join(s["body"].split()[:100])
            break

    outbound_links = _count_outbound_links(article)

    checks = [
        # (id, label, category, passed, weight)
        ("title_length", "Title is 50–60 characters", "seo", 50 <= len(title) <= 60, 8),
        ("title_has_number", "SEO title contains a number", "seo", _title_has_number(title), 8),
        ("meta_length", "Meta description is 150–160 characters", "seo", 150 <= len(meta) <= 160, 8),
        ("kw_in_title", "Primary keyword in title", "seo", keyword.lower() in title.lower(), 10),
        ("kw_in_intro", "Primary keyword in first 100 words", "seo", keyword.lower() in first_section_body.lower(), 8),
        ("kw_density", "Keyword density 1–3%", "seo", 1.0 <= density <= 3.0, 8),
        ("h2_count", "At least 4 H2 headings", "seo", h2_count >= 4, 7),
        ("word_count", "Word count 1000–2000", "seo", 1000 <= wc <= 2000, 10),
        ("internal_links", "3–5 internal links to patternslabco.com", "seo", 3 <= internal_links <= 7, 8),
        ("outbound_links", "At least 3 outbound links to external sources", "seo", outbound_links >= 3, 8),
        ("readability", "Average sentence length < 25 words", "seo", avg_sent < 25, 6),
        ("short_paragraphs", "No paragraph exceeds 3 sentences", "seo", not _has_long_paragraph(article), 6),
        ("schema_type", "Schema type identified", "seo", bool(article.get("schema_type")), 5),
        ("direct_answer", "At least one direct answer paragraph", "ai", _has_direct_answer(article), 7),
        ("has_list", "At least one numbered/bulleted list", "ai", _has_list(article), 7),
        ("has_faq", "FAQ section present (≥3 questions)", "ai", faq_count >= 3, 7),
        ("has_eeat", "E-E-A-T expertise signals present", "ai", _has_eeat(article), 7),
        ("schema_ready", "Article structure ready for rich results", "ai", faq_count >= 3 and bool(article.get("schema_type")), 4),
    ]

    total_weight = sum(c[4] for c in checks)
    earned = sum(c[4] for c in checks if c[3])
    score = round(earned / total_weight * 100)

    return {
        "score": score,
        "word_count": wc,
        "keyword_density": density,
        "internal_links": internal_links,
        "outbound_links": outbound_links,
        "h2_count": h2_count,
        "faq_count": faq_count,
        "avg_sentence_length": round(avg_sent, 1),
        "checks": [
            {"id": c[0], "label": c[1], "category": c[2], "passed": c[3], "weight": c[4]}
            for c in checks
        ],
    }
