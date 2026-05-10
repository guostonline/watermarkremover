import os
import json
import time
import re
import uuid
import logging
import requests
from pathlib import Path
from dotenv import load_dotenv
from flask import Blueprint, Flask, render_template, request, jsonify, Response, stream_with_context, send_from_directory

log = logging.getLogger(__name__)

import database as db
from modules.ai_client import AIClient
from modules.keyword_research import get_keyword_suggestions
from modules.web_researcher import research as web_research
from modules.site_context import refresh_site_context
from modules.article_generator import generate_article, regenerate_section
from modules.seo_checker import check_seo
from modules.seo_optimizer import optimize_stream as seo_optimize_stream

# --- Config ---
CONFIG_PATH = Path(__file__).parent / "config.json"
load_dotenv(Path(__file__).parent.parent / ".env")
with open(CONFIG_PATH) as f:
    CONFIG = json.load(f)

# Populate keys from environment if not already in config.json
for _env_key, _cfg_key in [("PEXELS_API_KEY", "pexels_api_key"),
                             ("OPENROUTER_API_KEY", "openrouter_api_key")]:
    if not CONFIG.get(_cfg_key):
        _val = os.environ.get(_env_key, "").strip()
        if _val:
            CONFIG[_cfg_key] = _val

article_bp = Blueprint("article", __name__, template_folder="templates", static_folder="static", static_url_path="/article/static")
article_bp = Blueprint("article", __name__, template_folder="templates", static_folder="static", static_url_path="/article/static")
app = Flask(__name__)
db.init_db()

ai = AIClient(CONFIG["openrouter_api_key"], CONFIG.get("openrouter_model", "google/gemini-2.0-flash-001"))

SITE_CACHE_TTL = 3600  # 1 hour


def _get_site_context():
    if db.get_site_context_age_seconds() > SITE_CACHE_TTL:
        return refresh_site_context(CONFIG, db)
    return db.get_site_context()


# --- SSE helper ---
def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


# ============================================================
# Pages
# ============================================================

@article_bp.route("/")
def index():
    return render_template("article_index.html", article_base="/article")


@article_bp.route("/history")
def history():
    articles = db.list_articles()
    return render_template("article_history.html", article_base="/article", articles=articles)


@article_bp.route("/view/<int:article_id>")
@article_bp.route("/article/<int:article_id>")
@article_bp.route("/<int:article_id>")
def view_article(article_id: int):
    article = db.get_article(article_id)
    if not article:
        return render_template("article_view.html", article_base="/article", article=None, not_found=True), 404
    return render_template("article_view.html", article_base="/article", article=article, not_found=False)


# ============================================================
# API — Settings
# ============================================================

@article_bp.route("/api/settings", methods=["GET"])
def api_get_settings():
    return jsonify({
        "openrouter_api_key": CONFIG.get("openrouter_api_key", ""),
        "openrouter_model":   CONFIG.get("openrouter_model", "google/gemini-2.0-flash-001"),
        "pexels_api_key":     CONFIG.get("pexels_api_key", ""),
        "pexels_api_key_set": bool((CONFIG.get("pexels_api_key") or "").strip()),
    })

@article_bp.route("/api/settings", methods=["POST"])
def api_save_settings():
    global CONFIG, ai
    data = request.json or {}
    allowed = {"openrouter_api_key", "openrouter_model", "pexels_api_key"}
    for key in allowed:
        if key not in data:
            continue

        # Do not overwrite existing keys with empty strings by accident.
        if key in {"openrouter_api_key", "pexels_api_key"}:
            val = (data.get(key) or "").strip()
            if val:
                CONFIG[key] = val
            continue

        CONFIG[key] = data[key]
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        import json as _json
        _json.dump(CONFIG, f, indent=2, ensure_ascii=False)
    # Reinitialise AI client with new credentials
    ai = AIClient(CONFIG["openrouter_api_key"], CONFIG.get("openrouter_model", "google/gemini-2.0-flash-001"))
    return jsonify({
        "ok": True,
        "saved": {
            "openrouter_model": CONFIG.get("openrouter_model", ""),
            "pexels_api_key_set": bool(CONFIG.get("pexels_api_key", "").strip()),
            "pexels_api_key_len": len((CONFIG.get("pexels_api_key") or "").strip()),
        }
    })


# ============================================================
# API — Keywords
# ============================================================

@article_bp.route("/api/keywords", methods=["POST"])
def api_keywords():
    keyword = (request.json or {}).get("keyword", "").strip()
    if not keyword:
        return jsonify({"error": "keyword required"}), 400

    cached = db.get_cached_keywords(keyword)
    if cached:
        return jsonify({"keywords": cached})

    keywords = get_keyword_suggestions(keyword, ai)
    db.set_cached_keywords(keyword, keywords)
    return jsonify({"keywords": keywords})


# ============================================================
# API — Site Context (products + posts)
# ============================================================

@article_bp.route("/api/site-context")
def api_site_context():
    force = request.args.get("force") == "1"
    if force:
        items = refresh_site_context(CONFIG, db)
    else:
        items = _get_site_context()
    products = [i for i in items if i["type"] == "product"]
    posts = [i for i in items if i["type"] == "post"]
    return jsonify({"products": products, "posts": posts, "total": len(items)})


# ============================================================
# API — Generate Article (SSE stream)
# ============================================================

@article_bp.route("/api/generate", methods=["POST"])
def api_generate():
    body = request.json or {}
    keyword = body.get("keyword", "").strip()
    selected_keywords = body.get("selected_keywords", [])

    if not keyword:
        return jsonify({"error": "keyword required"}), 400

    def generate():
        try:
            yield _sse("progress", {"step": "research", "message": "Searching the web for sources..."})

            research_results = web_research(keyword, max_sources=5)
            yield _sse("progress", {"step": "research_done",
                                    "message": f"Found {len(research_results)} sources",
                                    "sources": [{"url": r["url"], "domain": r["domain"]} for r in research_results]})

            yield _sse("progress", {"step": "context", "message": "Fetching products and posts from patternslabco.com..."})
            site_ctx = _get_site_context()
            products = [i for i in site_ctx if i["type"] == "product"]
            posts = [i for i in site_ctx if i["type"] == "post"]
            yield _sse("progress", {"step": "context_done",
                                    "message": f"Loaded {len(products)} products, {len(posts)} posts"})

            yield _sse("progress", {"step": "generating", "message": "Generating article with AI..."})
            article = generate_article(keyword, selected_keywords, research_results, site_ctx, ai)

            yield _sse("progress", {"step": "scoring", "message": "Running SEO check..."})
            seo = check_seo(article, keyword)
            article["seo_score"] = seo["score"]
            article["seo_details"] = seo
            article["keyword"] = keyword

            yield _sse("done", {"article": article})

        except Exception as e:
            yield _sse("error", {"message": str(e)})

    return Response(stream_with_context(generate()), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ============================================================
# API — Regenerate single section
# ============================================================

@article_bp.route("/api/regenerate-section", methods=["POST"])
def api_regenerate_section():
    body = request.json or {}
    keyword = body.get("keyword", "").strip()
    section = body.get("section", {})
    prev_heading = body.get("prev_heading", "")
    next_heading = body.get("next_heading", "")

    if not keyword or not section:
        return jsonify({"error": "keyword and section required"}), 400

    site_ctx = _get_site_context()
    try:
        new_section = regenerate_section(keyword, section, prev_heading, next_heading, site_ctx, ai)
        return jsonify({"section": new_section})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ============================================================
# API — Extend single section
# ============================================================

@article_bp.route("/api/extend-section", methods=["POST"])
def api_extend_section():
    body = request.json or {}
    keyword  = body.get("keyword", "").strip()
    section  = body.get("section", {})
    if not keyword or not section:
        return jsonify({"error": "keyword and section required"}), 400

    heading     = section.get("heading", "")
    current_body = section.get("body", "")
    word_count  = len(current_body.split())

    prompt = f"""You are extending a section of an SEO blog article.

KEYWORD: {keyword}
SECTION HEADING: {heading}
CURRENT BODY ({word_count} words):
{current_body}

Add 100–200 more words of valuable, natural-sounding content to this section.
Rules:
- Continue seamlessly from the existing text — do NOT repeat what is already written
- Stay on topic with the heading and keyword
- Use the same tone and style
- Add practical tips, examples, or elaboration
- Return ONLY the COMPLETE new body text (existing + new content combined), no JSON wrapper, no extra commentary."""

    try:
        extended = ai.chat(
            [{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=1200,
        )
        new_section = {**section, "body": extended.strip()}
        return jsonify({"section": new_section})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ============================================================
# API — Regenerate Title / Meta Description
# ============================================================

@article_bp.route("/api/regenerate-meta", methods=["POST"])
def api_regenerate_meta():
    body = request.json or {}
    keyword = body.get("keyword", "").strip()
    field = body.get("field", "")
    current_title = body.get("current_title", "")
    current_meta = body.get("current_meta", "")
    sections_summary = body.get("sections_summary", "")

    if not keyword or field not in ("title", "meta"):
        return jsonify({"error": "keyword and field (title|meta) required"}), 400

    if field == "title":
        prompt = (
            f"Write a new SEO title for a sewing blog article.\n"
            f"Primary keyword: {keyword}\n"
            f"Article sections cover: {sections_summary}\n"
            f"Current title: {current_title}\n\n"
            f"Requirements: 50–60 characters, include the primary keyword, compelling and click-worthy.\n"
            f"Return ONLY the title text, nothing else."
        )
    else:
        prompt = (
            f"Write a new meta description for a sewing blog article.\n"
            f"Primary keyword: {keyword}\n"
            f"Article sections cover: {sections_summary}\n"
            f"Current meta: {current_meta}\n\n"
            f"Requirements: 150–160 characters, include the primary keyword, end with a subtle call to action.\n"
            f"Return ONLY the meta description text, nothing else."
        )

    try:
        value = ai.chat(
            [{"role": "user", "content": prompt}],
            temperature=0.8,
            max_tokens=200,
        ).strip().strip('"').strip("'")
        return jsonify({"value": value})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ============================================================
# API — SEO Check
# ============================================================

@article_bp.route("/api/seo-check", methods=["POST"])
def api_seo_check():
    body = request.json or {}
    article = body.get("article", {})
    keyword = body.get("keyword", "").strip()

    if not article or not keyword:
        return jsonify({"error": "article and keyword required"}), 400

    result = check_seo(article, keyword)
    return jsonify(result)


# ============================================================
# API — Save Article
# ============================================================

@article_bp.route("/api/save", methods=["POST"])
def api_save():
    body = request.json or {}
    article = body.get("article", {})
    if not article:
        return jsonify({"error": "article required"}), 400

    article_id = body.get("id")
    if article_id:
        db.update_article(article_id, article)
        return jsonify({"id": article_id, "saved": True})
    else:
        new_id = db.save_article(article)
        return jsonify({"id": new_id, "saved": True})


# ============================================================
# API — Export
# ============================================================

@article_bp.route("/api/export/<int:article_id>")
def api_export(article_id: int):
    fmt = request.args.get("format", "html")
    article = db.get_article(article_id)
    if not article:
        return jsonify({"error": "not found"}), 404

    if fmt == "markdown":
        content = _to_markdown(article)
        return Response(content, mimetype="text/markdown",
                        headers={"Content-Disposition": f'attachment; filename="article-{article_id}.md"'})
    else:
        content = _to_html(article)
        return Response(content, mimetype="text/html",
                        headers={"Content-Disposition": f'attachment; filename="article-{article_id}.html"'})


def _to_html(article: dict) -> str:
    lines = []
    lines.append(f"<!-- SEO Title: {article.get('seo_title', '')} -->")
    lines.append(f"<!-- Meta Description: {article.get('meta_description', '')} -->")
    lines.append(f"<!-- Slug: {article.get('slug', '')} -->")
    lines.append("")
    for s in article.get("sections", []) or []:
        lvl = s.get("heading_level") or "h2"
        if s.get("heading"):
            lines.append(f"<{lvl}>{s['heading']}</{lvl}>")
        body = s.get("body") or ""
        # Convert markdown links to HTML
        body = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2">\1</a>', body)
        # Convert bold
        body = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', body)
        # Convert list items
        body = re.sub(r'^\s*[-*]\s+(.+)$', r'<li>\1</li>', body, flags=re.MULTILINE)
        body = re.sub(r'(<li>.*</li>)', r'<ul>\1</ul>', body, flags=re.DOTALL)
        # Wrap in paragraph
        lines.append(f"<p>{body}</p>")
        lines.append("")

    # FAQ section
    faq = article.get("faq", [])
    if faq:
        lines.append('<div class="faq-section">')
        lines.append("<h2>Frequently Asked Questions</h2>")
        for item in faq:
            lines.append(f"<h3>{item.get('question', '')}</h3>")
            lines.append(f"<p>{item.get('answer', '')}</p>")
        lines.append("</div>")

    # Schema markup
    schema_type = article.get("schema_type", "Article")
    if schema_type == "FAQPage" and faq:
        faq_schema = {
            "@context": "https://schema.org",
            "@type": "FAQPage",
            "mainEntity": [
                {"@type": "Question", "name": q["question"],
                 "acceptedAnswer": {"@type": "Answer", "text": q["answer"]}}
                for q in faq
            ]
        }
        lines.append(f'<script type="application/ld+json">{json.dumps(faq_schema, indent=2)}</script>')

    return "\n".join(lines)


def _to_markdown(article: dict) -> str:
    lines = []
    lines.append(f"# {article.get('seo_title') or ''}")
    lines.append(f"\n> {article.get('meta_description') or ''}\n")
    for s in article.get("sections", []) or []:
        lvl = s.get("heading_level") or "h2"
        prefix = "##" if lvl == "h2" else "###"
        if s.get("heading"):
            lines.append(f"\n{prefix} {s['heading']}\n")
        lines.append(s.get("body") or "")
        if s.get("image_prompt"):
            lines.append(f"\n*Image prompt: {s['image_prompt']}*\n")

    faq = article.get("faq", []) or []
    if faq:
        lines.append("\n## Frequently Asked Questions\n")
        for item in faq:
            lines.append(f"\n**{item.get('question') or ''}**\n\n{item.get('answer') or ''}\n")

    sources = article.get("sources", [])
    if sources:
        lines.append("\n## Sources\n")
        for url in sources:
            lines.append(f"- {url}")

    return "\n".join(lines)


# ============================================================
# API — Optimize SEO (fix failing checks)
# ============================================================

@article_bp.route("/api/optimize-seo", methods=["POST"])
def api_optimize_seo():
    body = request.json or {}
    article = body.get("article", {})
    keyword = body.get("keyword", "").strip()
    failed_ids = body.get("failed_ids", [])

    if not article or not keyword or not failed_ids:
        return jsonify({"error": "article, keyword and failed_ids required"}), 400

    site_ctx = _get_site_context()

    def stream():
        final_article = None
        for event in seo_optimize_stream(article, keyword, failed_ids, site_ctx, ai):
            if event["type"] == "done":
                final_article = event["article"]
                seo = check_seo(final_article, keyword)
                final_article["seo_score"] = seo["score"]
                final_article["seo_details"] = seo
                event["article"] = final_article
                event["seo"] = seo
            yield f"event: {event['type']}\ndata: {json.dumps(event)}\n\n"

    return Response(stream_with_context(stream()), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ============================================================
# API — Upload Image
# ============================================================

UPLOAD_DIR = Path(__file__).parent / "static" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif"}


def _to_webp(src_path: Path) -> Path:
    """Convert any image to WebP and delete the original if different format."""
    try:
        from PIL import Image
        img = Image.open(src_path)
        if img.mode in ("RGBA", "P", "LA"):
            img = img.convert("RGBA")
        else:
            img = img.convert("RGB")
        webp_path = src_path.with_suffix(".webp")
        img.save(webp_path, "webp", quality=85, method=6)
        if src_path.suffix.lower() != ".webp":
            src_path.unlink(missing_ok=True)
        return webp_path
    except ImportError:
        return src_path  # Pillow not installed — keep original
    except Exception:
        return src_path


@article_bp.route("/api/upload-image", methods=["POST"])
def api_upload_image():
    file = request.files.get("image")
    if not file or not file.filename:
        return jsonify({"error": "No file provided"}), 400

    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        return jsonify({"error": f"File type {ext} not allowed"}), 400

    stem = uuid.uuid4().hex
    tmp_path = UPLOAD_DIR / f"{stem}{ext}"
    file.save(tmp_path)

    final_path = _to_webp(tmp_path)
    filename = final_path.name

    return jsonify({
        "url": f"/article/static/uploads/{filename}",
        "filename": filename,
        "original": file.filename,
        "format": "webp",
    })


@article_bp.route("/api/pexels/auto-cover", methods=["POST"])
@article_bp.route("/pexels/auto-cover", methods=["POST"])
def api_pexels_auto_cover():
    pexels_key = CONFIG.get("pexels_api_key", "").strip()
    if not pexels_key:
        return jsonify({"error": "Pexels API key is not set in Settings."}), 400

    body = request.json or {}
    query = (body.get("query") or "").strip()
    if not query:
        return jsonify({"error": "query is required"}), 400

    try:
        resp = requests.get(
            "https://api.pexels.com/v1/search",
            headers={"Authorization": pexels_key},
            params={
                "query": query,
                "orientation": "landscape",
                "per_page": 6,
                "page": 1,
            },
            timeout=20,
        )
        if resp.status_code != 200:
            return jsonify({"error": f"Pexels API error ({resp.status_code})"}), 502

        data = resp.json()
        photos = data.get("photos") or []
        if not photos:
            return jsonify({"error": "No image found for this query."}), 404

        p = photos[0]
        src = p.get("src") or {}
        image_url = src.get("landscape") or src.get("large2x") or src.get("large") or src.get("original")
        return jsonify({
            "ok": True,
            "image_url": image_url,
            "alt": p.get("alt") or query,
            "pexels_url": p.get("url") or "",
            "photographer": p.get("photographer") or "",
            "photographer_url": p.get("photographer_url") or "",
        })
    except requests.RequestException as e:
        return jsonify({"error": f"Failed to contact Pexels: {e}"}), 502


@article_bp.route("/static/uploads/<filename>")
def uploaded_file(filename):
    return send_from_directory(UPLOAD_DIR, filename)


def _upload_image_to_wp(wp_url: str, wp_user: str, wp_pass: str, image_path: Path, filename: str) -> dict | None:
    """Upload an image to WordPress media library and return media metadata."""
    import requests as req
    from requests.auth import HTTPBasicAuth
    try:
        with open(image_path, "rb") as f:
            files = {"file": (filename, f, "image/webp")}
            resp = req.post(
                f"{wp_url}/wp-json/wp/v2/media",
                auth=HTTPBasicAuth(wp_user, wp_pass),
                files=files,
                timeout=30,
            )
        if resp.status_code in (200, 201):
            data = resp.json()
            return {
                "id": data.get("id"),
                "url": data.get("source_url"),
            }
        log.warning("WP local media upload failed: %s %s", resp.status_code, resp.text[:200])
    except Exception as e:
        log.warning("WP local media upload exception: %s", e)
    return None


def _upload_image_url_to_wp(wp_url: str, wp_user: str, wp_pass: str, image_url: str, filename_hint: str = "cover.webp") -> dict | None:
    """Download an external image URL and upload it to WordPress media."""
    import requests as req
    from requests.auth import HTTPBasicAuth

    try:
        dl = req.get(image_url, timeout=30)
        if dl.status_code != 200 or not dl.content:
            log.warning("Failed to download image %s: status %s", image_url, dl.status_code)
            return None

        content_type = dl.headers.get("content-type", "image/jpeg").split(";")[0].strip()
        _ext_map = {"image/jpeg": ".jpg", "image/jpg": ".jpg", "image/png": ".png",
                    "image/webp": ".webp", "image/gif": ".gif", "image/avif": ".avif"}
        ext = _ext_map.get(content_type) or Path(filename_hint).suffix.lower() or ".jpg"
        if ext not in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif"}:
            ext = ".jpg"
        filename = f"{uuid.uuid4().hex}{ext}"

        files = {"file": (filename, dl.content, content_type)}
        resp = req.post(
            f"{wp_url}/wp-json/wp/v2/media",
            auth=HTTPBasicAuth(wp_user, wp_pass),
            files=files,
            timeout=30,
        )
        if resp.status_code in (200, 201):
            data = resp.json()
            return {"id": data.get("id"), "url": data.get("source_url")}
        log.warning("WP media upload failed: %s %s", resp.status_code, resp.text[:200])
    except Exception as e:
        log.warning("WP media upload exception: %s", e)
    return None


def _article_to_wp_html(article: dict, wp_image_urls: dict) -> str:
    """Convert article to clean WordPress block HTML with images embedded."""
    lines = []

    _orig_cover = article.get("cover_image_url", "")
    cover_url = wp_image_urls.get("cover") or (
        _orig_cover if str(_orig_cover).startswith(("http://", "https://")) else None
    )
    if cover_url:
        lines.append(f'<!-- wp:image {{"size":"full"}} --><figure class="wp-block-image"><img src="{cover_url}" alt="{article.get("seo_title", "")}" loading="lazy"/></figure><!-- /wp:image -->')
        lines.append("")

    for s in article.get("sections", []) or []:
        lvl = s.get("heading_level") or "h2"
        if s.get("heading"):
            lines.append(f"<!-- wp:heading --><{lvl}>{s['heading']}</{lvl}><!-- /wp:heading -->")
        body = s.get("body") or ""
        body = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2">\1</a>', body)
        body = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', body)
        list_items = re.findall(r'^\s*[-*\d.]+\s+(.+)$', body, re.MULTILINE)
        if list_items:
            before = re.split(r'\n\s*[-*\d.]+\s+', body)[0].strip()
            li_html = "".join(f"<li>{item}</li>" for item in list_items)
            after_parts = body.split("\n")
            after = " ".join(l for l in after_parts if not re.match(r'^\s*[-*\d.]', l) and l.strip() and l.strip() != before.split("\n")[-1])
            if before:
                lines.append(f"<!-- wp:paragraph --><p>{before}</p><!-- /wp:paragraph -->")
            lines.append(f"<!-- wp:list --><ul>{li_html}</ul><!-- /wp:list -->")
        else:
            lines.append(f"<!-- wp:paragraph --><p>{body}</p><!-- /wp:paragraph -->")

        section_key = f"section_{s.get('_idx', '')}"
        _orig_sec = s.get("image_url", "")
        sec_url = wp_image_urls.get(section_key) or (
            _orig_sec if str(_orig_sec).startswith(("http://", "https://")) else None
        )
        if sec_url:
            img_w, img_h = 800, 533
            lines.append(f'<!-- wp:image {{"size":"large"}} --><figure class="wp-block-image size-large"><img src="{sec_url}" alt="{s.get("heading", "")}" width="{img_w}" height="{img_h}" loading="lazy"/></figure><!-- /wp:image -->')
            lines.append("")

    faq = article.get("faq", []) or []
    if faq:
        lines.append("<!-- wp:heading --><h2>Frequently Asked Questions</h2><!-- /wp:heading -->")
        for item in faq:
            q = item.get("question") or ""
            a = item.get("answer") or ""
            lines.append(f"<!-- wp:heading {{\"level\":3}} --><h3>{q}</h3><!-- /wp:heading -->")
            lines.append(f"<!-- wp:paragraph --><p>{a}</p><!-- /wp:paragraph -->")

    return "\n".join(lines)


@article_bp.route("/api/publish-wordpress", methods=["POST"])
def api_publish_wordpress():
    body = request.json or {}
    article = body.get("article", {})
    status = body.get("status", "draft")

    if not article:
        return jsonify({"error": "article required"}), 400

    return _publish_article_to_wordpress(article, status)


@article_bp.route("/api/publish-wordpress/<int:article_id>", methods=["POST"])
def api_publish_wordpress_by_id(article_id: int):
    body = request.json or {}
    status = body.get("status", "draft")
    article = db.get_article(article_id)
    if not article:
        return jsonify({"error": "article not found"}), 404
    return _publish_article_to_wordpress(article, status)


def _publish_article_to_wordpress(article: dict, status: str = "draft"):
    import requests as req
    from requests.auth import HTTPBasicAuth

    wp_url = CONFIG.get("wc_url", "").rstrip("/")
    wp_user = CONFIG.get("wp_username", "")
    wp_pass = CONFIG.get("wp_app_password", "")

    if not wp_url or not wp_user or not wp_pass:
        return jsonify({"error": "WordPress credentials not configured"}), 500

    wp_image_urls = {}
    featured_media_id = None

    def _local_upload_filename(url: str) -> str | None:
        if not url:
            return None
        if url.startswith("/article/static/uploads/"):
            return Path(url).name
        if url.startswith("/static/uploads/"):
            return Path(url).name
        return None

    cover_url_local = article.get("cover_image_url")
    cover_filename = _local_upload_filename(cover_url_local)
    if cover_filename:
        filename = cover_filename
        local_path = UPLOAD_DIR / filename
        if local_path.exists():
            wp_cover_media = _upload_image_to_wp(wp_url, wp_user, wp_pass, local_path, filename)
            if wp_cover_media and wp_cover_media.get("url"):
                wp_image_urls["cover"] = wp_cover_media["url"]
                featured_media_id = wp_cover_media.get("id")
    elif cover_url_local and str(cover_url_local).startswith(("http://", "https://")):
        wp_cover_media = _upload_image_url_to_wp(wp_url, wp_user, wp_pass, str(cover_url_local), "cover.webp")
        if wp_cover_media and wp_cover_media.get("url"):
            wp_image_urls["cover"] = wp_cover_media["url"]
            featured_media_id = wp_cover_media.get("id")

    for idx, s in enumerate((article.get("sections") or [])):
        img_url = s.get("image_url")
        sec_filename = _local_upload_filename(img_url)
        if sec_filename:
            filename = sec_filename
            local_path = UPLOAD_DIR / filename
            if local_path.exists():
                s["_idx"] = idx
                wp_sec_media = _upload_image_to_wp(wp_url, wp_user, wp_pass, local_path, filename)
                if wp_sec_media and wp_sec_media.get("url"):
                    wp_image_urls[f"section_{idx}"] = wp_sec_media["url"]
        elif img_url and str(img_url).startswith(("http://", "https://")):
            s["_idx"] = idx
            wp_sec_media = _upload_image_url_to_wp(wp_url, wp_user, wp_pass, str(img_url), f"section-{idx}.webp")
            if wp_sec_media and wp_sec_media.get("url"):
                wp_image_urls[f"section_{idx}"] = wp_sec_media["url"]

    content_html = _article_to_wp_html(article, wp_image_urls)

    payload = {
        "title": article.get("seo_title") or "",
        "content": content_html,
        "excerpt": article.get("meta_description") or "",
        "slug": article.get("slug") or "",
        "status": status,
    }
    if featured_media_id:
        payload["featured_media"] = featured_media_id

    try:
        resp = req.post(
            f"{wp_url}/wp-json/wp/v2/posts",
            json=payload,
            auth=HTTPBasicAuth(wp_user, wp_pass),
            timeout=20,
        )
        if resp.status_code in (200, 201):
            data = resp.json()
            return jsonify({
                "success": True,
                "post_id": data.get("id"),
                "post_url": data.get("link"),
                "edit_url": f"{wp_url}/wp-admin/post.php?post={data.get('id')}&action=edit",
                "status": data.get("status"),
                "images_uploaded": len(wp_image_urls),
            })
        else:
            return jsonify({"error": f"WordPress API error {resp.status_code}: {resp.text[:300]}"}), 502
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.register_blueprint(article_bp)
    app.run(debug=True, port=5001, threaded=True)
