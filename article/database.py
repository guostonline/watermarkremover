import sqlite3
import json
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "articles.db"


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS site_context (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT NOT NULL,
                title TEXT,
                type TEXT,
                categories TEXT,
                cached_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS articles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                keyword TEXT,
                seo_title TEXT,
                meta_description TEXT,
                slug TEXT,
                sections TEXT,
                faq TEXT,
                sources TEXT,
                word_count INTEGER DEFAULT 0,
                seo_score INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS keyword_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                seed_keyword TEXT UNIQUE,
                keywords TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
        """)


# --- site_context helpers ---

def clear_site_context():
    with get_conn() as conn:
        conn.execute("DELETE FROM site_context")


def insert_site_items(items: list[dict]):
    with get_conn() as conn:
        conn.executemany(
            "INSERT INTO site_context (url, title, type, categories, cached_at) VALUES (?,?,?,?,?)",
            [(i["url"], i["title"], i["type"], json.dumps(i.get("categories", [])), datetime.utcnow().isoformat())
             for i in items]
        )


def get_site_context() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT url, title, type, categories FROM site_context").fetchall()
    return [{"url": r["url"], "title": r["title"], "type": r["type"],
             "categories": json.loads(r["categories"] or "[]")} for r in rows]


def get_site_context_age_seconds() -> float:
    with get_conn() as conn:
        row = conn.execute("SELECT cached_at FROM site_context ORDER BY id DESC LIMIT 1").fetchone()
    if not row:
        return float("inf")
    cached = datetime.fromisoformat(row["cached_at"])
    return (datetime.utcnow() - cached).total_seconds()


# --- articles helpers ---

def save_article(data: dict) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO articles
               (keyword, seo_title, meta_description, slug, sections, faq, sources, word_count, seo_score)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (data["keyword"], data["seo_title"], data["meta_description"], data["slug"],
             json.dumps(data.get("sections", [])), json.dumps(data.get("faq", [])),
             json.dumps(data.get("sources", [])), data.get("word_count", 0), data.get("seo_score", 0))
        )
        return cur.lastrowid


def update_article(article_id: int, data: dict):
    with get_conn() as conn:
        conn.execute(
            """UPDATE articles SET keyword=?, seo_title=?, meta_description=?, slug=?,
               sections=?, faq=?, sources=?, word_count=?, seo_score=?, updated_at=?
               WHERE id=?""",
            (data["keyword"], data["seo_title"], data["meta_description"], data["slug"],
             json.dumps(data.get("sections", [])), json.dumps(data.get("faq", [])),
             json.dumps(data.get("sources", [])), data.get("word_count", 0), data.get("seo_score", 0),
             datetime.utcnow().isoformat(), article_id)
        )


def get_article(article_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM articles WHERE id=?", (article_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    d["sections"] = json.loads(d["sections"] or "[]")
    d["faq"] = json.loads(d["faq"] or "[]")
    d["sources"] = json.loads(d["sources"] or "[]")
    return d


def list_articles() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, keyword, seo_title, word_count, seo_score, created_at FROM articles ORDER BY id DESC"
        ).fetchall()
    return [dict(r) for r in rows]


# --- keyword cache helpers ---

def get_cached_keywords(seed: str) -> list | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT keywords, created_at FROM keyword_cache WHERE seed_keyword=?", (seed.lower(),)
        ).fetchone()
    if not row:
        return None
    age = (datetime.utcnow() - datetime.fromisoformat(row["created_at"])).total_seconds()
    if age > 86400:  # 24h cache
        return None
    return json.loads(row["keywords"])


def set_cached_keywords(seed: str, keywords: list):
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO keyword_cache (seed_keyword, keywords, created_at) VALUES (?,?,?)",
            (seed.lower(), json.dumps(keywords), datetime.utcnow().isoformat())
        )
