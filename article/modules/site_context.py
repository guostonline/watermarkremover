import requests
from requests.auth import HTTPBasicAuth

TIMEOUT = 15
HEADERS = {"User-Agent": "PatternsLab Article Generator/1.0"}


def fetch_wp_posts(wc_url: str) -> list[dict]:
    """Fetch all published WordPress posts via REST API (public endpoint)."""
    items = []
    page = 1
    while True:
        try:
            resp = requests.get(
                f"{wc_url}/wp-json/wp/v2/posts",
                params={"per_page": 100, "page": page, "status": "publish", "_fields": "id,link,title,categories"},
                headers=HEADERS,
                timeout=TIMEOUT,
            )
            if resp.status_code != 200:
                break
            data = resp.json()
            if not data:
                break
            for post in data:
                items.append({
                    "url": post.get("link", ""),
                    "title": post.get("title", {}).get("rendered", ""),
                    "type": "post",
                    "categories": post.get("categories", []),
                })
            total_pages = int(resp.headers.get("X-WP-TotalPages", 1))
            if page >= total_pages:
                break
            page += 1
        except Exception:
            break
    return items


def fetch_wc_products(wc_url: str, wc_key: str, wc_secret: str) -> list[dict]:
    """Fetch all WooCommerce products via REST API (requires auth)."""
    items = []
    page = 1
    auth = HTTPBasicAuth(wc_key, wc_secret)
    while True:
        try:
            resp = requests.get(
                f"{wc_url}/wp-json/wc/v3/products",
                params={"per_page": 100, "page": page, "status": "publish",
                        "_fields": "id,name,permalink,categories,price"},
                auth=auth,
                headers=HEADERS,
                timeout=TIMEOUT,
            )
            if resp.status_code != 200:
                break
            data = resp.json()
            if not data:
                break
            for product in data:
                cats = [c.get("name", "") for c in product.get("categories", [])]
                items.append({
                    "url": product.get("permalink", ""),
                    "title": product.get("name", ""),
                    "type": "product",
                    "categories": cats,
                    "price": product.get("price", ""),
                })
            total_pages = int(resp.headers.get("X-WP-TotalPages", 1))
            if page >= total_pages:
                break
            page += 1
        except Exception:
            break
    return items


def refresh_site_context(config: dict, db_module) -> list[dict]:
    """Fetch posts + products, store in DB, return combined list."""
    posts = fetch_wp_posts(config["wc_url"])
    products = fetch_wc_products(config["wc_url"], config["wc_key"], config["wc_secret"])
    all_items = posts + products
    db_module.clear_site_context()
    if all_items:
        db_module.insert_site_items(all_items)
    return all_items
