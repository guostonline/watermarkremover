# PatternsLab Article Generator

## What It Does
A Flask web app that generates 1000–2000 word SEO-optimized blog articles for patternslabco.com (WordPress + WooCommerce). It researches topics from the web, embeds internal links, and scores content against SEO and AI-search criteria.

**Site context:**
- URL: https://patternslabco.com
- Platform: WordPress + WooCommerce
- Products: 39 PDF sewing patterns ($3–$8), product URL: `/product/[slug]/`
- Blog: 6 posts, URL: `/[post-slug]/`
- WP Posts API: `GET /wp-json/wp/v2/posts` — public
- WC Products API: `GET /wp-json/wc/v3/products` — requires auth

**Stack:** Python 3.11+, Flask, SQLite, OpenRouter → `google/gemini-3.1-flash-lite-preview`, requests + BeautifulSoup + DuckDuckGo HTML search, vanilla HTML/CSS/JS.

---

## Features

### F1 — Keyword Research
- Text field for primary keyword
- **[Find Keywords]** button: AI suggests 15 long-tail keywords with intent labels
- Selectable keyword pills feed into article generation

### F2 — Web Research with Citations
- DuckDuckGo search for top 5 URLs on the keyword
- BeautifulSoup extracts text from each URL
- Gemini summarizes + cites sources in the article

### F3 — Internal Links
- Fetches all WP posts + WC products via REST API (cached 1h in SQLite)
- AI embeds 3–5 contextual internal links naturally in article body

### F4 — Article Generation (1000–2000 words)
- SEO title (50–60 chars), meta description (150–160 chars), slug
- Structure: intro + 5–7 H2 sections + FAQ (3–5 Q&A) + conclusion
- Per-section: heading, body, image prompt, cited sources

### F5 — Paragraph-Level Editor
- Each section as an editable card
- **[↻ Regenerate]** re-generates only that section
- **[🖼 Image Prompt]** toggles the Midjourney/DALL-E prompt
- Source citations badge per paragraph

### F6 — SEO + AI Visibility Checker (0–100 score)
**SEO checks:** title length, meta length, keyword in title/intro, keyword density, H2 count, word count, internal links, readability

**AI/GEO checks:** direct answers, lists, FAQ presence, E-E-A-T signals, schema type

### F7 — Save & Export
- SQLite storage for all generated articles
- Export as WordPress-ready HTML or clean Markdown
- History page with date, keyword, SEO score, word count

---

## Database Schema

```sql
CREATE TABLE site_context (id, url, title, type, categories, cached_at);
CREATE TABLE articles (id, keyword, seo_title, meta_description, slug, sections, faq, sources, word_count, seo_score, created_at, updated_at);
CREATE TABLE keyword_cache (id, seed_keyword, keywords, created_at);
```

---

## API Routes

| Method | Route | Description |
|--------|-------|-------------|
| GET | `/` | Main article generator UI |
| POST | `/api/keywords` | AI keyword suggestions |
| POST | `/api/generate` | Generate article (SSE stream) |
| POST | `/api/regenerate-section` | Regenerate single paragraph |
| POST | `/api/seo-check` | SEO + GEO scoring |
| POST | `/api/save` | Save to SQLite |
| GET | `/api/site-context` | Cached products + posts |
| GET | `/history` | Article history page |
| GET | `/api/export/<id>` | Export HTML or Markdown |