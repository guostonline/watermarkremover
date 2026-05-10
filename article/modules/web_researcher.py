import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse


HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
}
MAX_CHARS_PER_PAGE = 3000
TIMEOUT = 10


def ddg_search(query: str, max_results: int = 5) -> list[str]:
    """Search DuckDuckGo HTML and return a list of result URLs."""
    url = "https://html.duckduckgo.com/html/"
    try:
        resp = requests.post(url, data={"q": query}, headers=HEADERS, timeout=TIMEOUT)
        soup = BeautifulSoup(resp.text, "lxml")
        links = []
        for a in soup.select("a.result__url"):
            href = a.get("href", "")
            if href.startswith("http"):
                parsed = urlparse(href)
                # Skip DDG redirect URLs and known bad domains
                if parsed.netloc and "duckduckgo" not in parsed.netloc:
                    links.append(href)
                    if len(links) >= max_results:
                        break
        # Fallback: try result__a links
        if not links:
            for a in soup.select("a.result__a"):
                href = a.get("href", "")
                if href.startswith("http") and "duckduckgo" not in href:
                    links.append(href)
                    if len(links) >= max_results:
                        break
        return links
    except Exception:
        return []


def fetch_page_text(url: str) -> str:
    """Fetch a URL and return clean article text."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        # Remove noise
        for tag in soup(["script", "style", "nav", "header", "footer", "aside",
                          "form", "iframe", "noscript", "ads"]):
            tag.decompose()
        # Try article / main first, else body
        content = soup.find("article") or soup.find("main") or soup.find("body")
        if not content:
            return ""
        text = re.sub(r"\n{3,}", "\n\n", content.get_text(separator="\n"))
        return text[:MAX_CHARS_PER_PAGE].strip()
    except Exception:
        return ""


def research(keyword: str, max_sources: int = 5) -> list[dict]:
    """Search DuckDuckGo and scrape top results. Returns list of {url, domain, text}."""
    urls = ddg_search(keyword + " sewing tutorial", max_results=max_sources)
    results = []
    for url in urls:
        text = fetch_page_text(url)
        if len(text) > 200:
            domain = urlparse(url).netloc.replace("www.", "")
            results.append({"url": url, "domain": domain, "text": text})
    return results
