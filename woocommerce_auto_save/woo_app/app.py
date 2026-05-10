import base64
import csv
import hashlib
import io
import json
import os
import queue
import re
import threading
import time
import unicodedata
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

import fitz
import requests
from flask import Flask, Response, jsonify, render_template, request, send_from_directory
from PIL import Image, ImageStat


ROOT = Path(__file__).resolve().parent
EXPORT_DIR = ROOT / "_wc_importer_output"
IMAGE_DIR = EXPORT_DIR / "images"
CANDIDATE_DIR = EXPORT_DIR / "candidates"
IMAGE_DIR.mkdir(parents=True, exist_ok=True)
CANDIDATE_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_SHEET_URL = "https://docs.google.com/spreadsheets/d/19CAAFREkUgHOCjhSGrPHeHeMM6uYT_LeJ9o6XpXuy0Q/edit?usp=sharing"
CONFIG_PATH = ROOT / "config.json"

app = Flask(__name__)
jobs: dict[str, queue.Queue] = {}


def load_config() -> dict[str, str]:
    defaults = {
        "sheet_url": DEFAULT_SHEET_URL,
        "wc_url": "",
        "wc_key": "",
        "wc_secret": "",
        "wp_username": "",
        "wp_app_password": "",
        "price": "6.99",
        "status": "draft",
        "default_category": "",
        "openrouter_api_key": "",
        "openrouter_model": "openai/gpt-4o-mini",
    }
    if CONFIG_PATH.exists():
        with CONFIG_PATH.open("r", encoding="utf-8") as fh:
            defaults.update(json.load(fh))
    for key, value in os.environ.items():
        lower = key.lower()
        if lower in defaults:
            defaults[lower] = value
    return {key: str(value).strip() for key, value in defaults.items()}


def config_status() -> dict[str, Any]:
    config = load_config()
    required = ["sheet_url", "wc_url", "wc_key", "wc_secret", "wp_username", "wp_app_password"]
    missing = [key for key in required if not config.get(key)]
    return {
        "file": str(CONFIG_PATH),
        "loaded": CONFIG_PATH.exists(),
        "missing": missing,
        "store": config.get("wc_url", ""),
        "status": config.get("status", "draft"),
        "price": config.get("price", "6.99"),
        "ai": bool(config.get("openrouter_api_key")),
    }


@dataclass
class ProductFolder:
    folder: str
    path: str
    number: int | None
    clean_name: str
    pdfs: list[str]
    warnings: list[str]


def natural_key(path: Path) -> tuple[int, str]:
    m = re.match(r"^\s*(\d+)", path.name)
    return (int(m.group(1)) if m else 999999, path.name.lower())


def clean_folder_name(name: str) -> tuple[int | None, str]:
    m = re.match(r"^\s*(\d+)\s*[-]?\s*(.*)$", name)
    if not m:
        return None, name.strip()
    label = m.group(2).strip() or name.strip()
    return int(m.group(1)), label


def scan_folders() -> list[ProductFolder]:
    products: list[ProductFolder] = []
    for folder in sorted([p for p in ROOT.iterdir() if p.is_dir() and not p.name.startswith("_")], key=natural_key):
        pdfs = sorted(folder.glob("*.pdf"), key=lambda p: p.name.lower())
        if not pdfs:
            continue
        number, clean_name = clean_folder_name(folder.name)
        warnings = []
        if len(pdfs) != 3:
            warnings.append(f"Found {len(pdfs)} PDFs, expected 3.")
        products.append(
            ProductFolder(
                folder=folder.name,
                path=str(folder),
                number=number,
                clean_name=clean_name,
                pdfs=[p.name for p in pdfs],
                warnings=warnings,
            )
        )
    return products


def sheet_csv_url(sheet_url: str) -> str:
    match = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", sheet_url)
    if not match:
        return sheet_url
    return f"https://docs.google.com/spreadsheets/d/{match.group(1)}/export?format=csv"


def normalize_key(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "", ascii_value.lower())


def load_sheet(sheet_url: str) -> list[dict[str, str]]:
    url = sheet_csv_url(sheet_url)
    last_error = None
    for _ in range(3):
        try:
            response = requests.get(url, timeout=45)
            response.raise_for_status()
            text = response.content.decode("utf-8-sig", errors="replace")
            return list(csv.DictReader(io.StringIO(text)))
        except Exception as exc:
            last_error = exc
            time.sleep(2)
    raise RuntimeError(f"Could not read Google Sheet CSV: {last_error}")


def pick_field(row: dict[str, str], names: list[str]) -> str:
    by_norm = {normalize_key(k): v for k, v in row.items()}
    for name in names:
        value = by_norm.get(normalize_key(name))
        if value:
            return value.strip()
    return ""


def match_sheet_row(product: ProductFolder, rows: list[dict[str, str]], index: int) -> dict[str, str]:
    if not rows:
        return {}
    product_name = normalize_key(product.clean_name)
    for row in rows:
        folder_name = pick_field(row, ["Ton Pattern (Dossier)", "folder", "dossier", "pattern"])
        folder_key = normalize_key(folder_name)
        if folder_key and (product_name == folder_key or product_name in folder_key or folder_key in product_name):
            return row
    for row in rows:
        title = pick_field(row, ["Titre IndiePattern", "title", "name", "product title"])
        if title and product_name in normalize_key(title):
            return row
    for row in rows:
        row_id = pick_field(row, ["id", "number", "num", "#", "product number"])
        sheet_number = product.number + 1 if product.number is not None else None
        if row_id and sheet_number is not None and re.search(rf"\b{sheet_number}\b", row_id):
            return row
    return rows[index] if index < len(rows) else {}


def selected_guide_pdf(folder: Path) -> Path:
    pdfs = sorted(folder.glob("*.pdf"), key=lambda p: p.name.lower())
    guide = [p for p in pdfs if re.search(r"sew|guide|instruction", p.name, re.I)]
    return guide[0] if guide else pdfs[0]


def save_embedded_image(image_bytes: bytes, out: Path) -> None:
    with Image.open(io.BytesIO(image_bytes)) as image:
        if image.mode in ("RGBA", "LA"):
            background = Image.new("RGB", image.size, (255, 255, 255))
            background.paste(image, mask=image.getchannel("A"))
            image = background
        elif image.mode != "RGB":
            image = image.convert("RGB")
        image.save(out, "JPEG", quality=92, optimize=True)


def image_is_useful(image_bytes: bytes) -> bool:
    try:
        with Image.open(io.BytesIO(image_bytes)) as image:
            sample = image.convert("RGB").resize((64, 64))
            stats = ImageStat.Stat(sample)
            mean = sum(stats.mean) / 3
            stddev = sum(stats.stddev) / 3
            extrema = sample.getextrema()
    except Exception:
        return False
    if mean < 8 or mean > 248:
        return False
    if stddev < 6:
        return False
    if all((high - low) < 12 for low, high in extrema):
        return False
    return True


def embedded_pdf_images(folder: Path) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for pdf in sorted(folder.glob("*.pdf"), key=lambda p: p.name.lower()):
        try:
            doc = fitz.open(pdf)
        except Exception:
            continue
        for page_index, page in enumerate(doc):
            for image_index, image_ref in enumerate(page.get_images(full=True)):
                xref = image_ref[0]
                try:
                    info = doc.extract_image(xref)
                except Exception:
                    continue
                image_bytes = info.get("image") or b""
                width = int(info.get("width") or 0)
                height = int(info.get("height") or 0)
                if width < 450 or height < 450 or width * height < 250_000:
                    continue
                if not image_is_useful(image_bytes):
                    continue
                digest = hashlib.sha1(image_bytes).hexdigest()
                if digest in seen:
                    continue
                seen.add(digest)
                ext = (info.get("ext") or "").lower()
                name_bonus = 250_000 if re.search(r"a0|a4|letter|patterns?", pdf.name, re.I) else 0
                jpeg_bonus = 180_000 if ext in ("jpg", "jpeg") else 0
                early_page_bonus = max(0, 80_000 - page_index * 10_000)
                score = (width * height) + len(image_bytes) + name_bonus + jpeg_bonus + early_page_bonus
                candidates.append(
                    {
                        "pdf": pdf,
                        "page": page_index,
                        "image_index": image_index,
                        "width": width,
                        "height": height,
                        "bytes": image_bytes,
                        "score": score,
                    }
                )
        doc.close()
    candidates.sort(key=lambda item: item["score"], reverse=True)
    return candidates


def extract_model_images(folder: Path, force: bool = False) -> list[str]:
    safe = re.sub(r"[^a-zA-Z0-9_-]+", "-", folder.name).strip("-")
    existing = [IMAGE_DIR / f"{safe}-model-1.jpg", IMAGE_DIR / f"{safe}-model-2.jpg"]
    if all(p.exists() for p in existing) and not force:
        return [f"/output/images/{p.name}" for p in existing]

    embedded = embedded_pdf_images(folder)
    urls = []
    for out_index, candidate in enumerate(embedded[:2], start=1):
        out = IMAGE_DIR / f"{safe}-model-{out_index}.jpg"
        save_embedded_image(candidate["bytes"], out)
        urls.append(f"/output/images/{out.name}")
    if len(urls) >= 2:
        return urls

    pdf = selected_guide_pdf(folder)
    doc = fitz.open(pdf)
    page_indexes = list(range(min(len(doc), 6)))
    if len(page_indexes) == 1:
        page_indexes = [0, 0]
    for out_index, page_index in enumerate(page_indexes[:2], start=1):
        page = doc.load_page(page_index)
        pix = page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0), alpha=False)
        out = IMAGE_DIR / f"{safe}-model-{out_index}.jpg"
        pix.save(out)
        urls.append(f"/output/images/{out.name}")
    doc.close()
    return urls


def extract_candidate_images(folder: Path, force: bool = False, limit: int = 16) -> list[dict[str, Any]]:
    safe = re.sub(r"[^a-zA-Z0-9_-]+", "-", folder.name).strip("-")
    candidates = embedded_pdf_images(folder)
    output: list[dict[str, Any]] = []
    for out_index, candidate in enumerate(candidates[:limit], start=1):
        out = CANDIDATE_DIR / f"{safe}-choice-{out_index}.jpg"
        if force or not out.exists():
            save_embedded_image(candidate["bytes"], out)
        output.append(
            {
                "url": f"/output/candidates/{out.name}",
                "file": out.name,
                "pdf": candidate["pdf"].name,
                "page": candidate["page"] + 1,
                "width": candidate["width"],
                "height": candidate["height"],
            }
        )
    return output


def product_preview(
    product: ProductFolder,
    row: dict[str, str],
    extra_warnings: list[str] | None = None,
    selected_images: list[str] | None = None,
) -> dict[str, Any]:
    title = pick_field(row, ["Titre IndiePattern", "title", "name", "product title"]) or product.clean_name
    description = pick_field(row, ["Description Complète", "description complete", "description", "desc"])
    tags_text = pick_field(row, ["Mots-clés Inclus", "mots cles inclus", "tags", "tag"])
    tags = [t.strip() for t in re.split(r"[,;|]", tags_text) if t.strip()]
    choices = extract_candidate_images(Path(product.path))
    images = selected_images or [choice["url"] for choice in choices[:2]] or extract_model_images(Path(product.path))
    return {
        "folder": product.folder,
        "title": title,
        "description": description,
        "tags": tags,
        "price": load_config().get("price", "6.99"),
        "category": load_config().get("default_category", ""),
        "images": images,
        "image_choices": choices,
        "pdfs": product.pdfs,
        "warnings": product.warnings + (extra_warnings or []),
    }


def auth_header(username: str, app_password: str) -> dict[str, str]:
    token = base64.b64encode(f"{username}:{app_password.replace(' ', '')}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def upload_media(wp_url: str, username: str, app_password: str, file_path: Path) -> dict[str, Any]:
    endpoint = wp_url.rstrip("/") + "/wp-json/wp/v2/media"
    headers = auth_header(username, app_password)
    headers["Content-Disposition"] = f'attachment; filename="{file_path.name}"'
    mime = "application/pdf" if file_path.suffix.lower() == ".pdf" else "image/jpeg"
    headers["Content-Type"] = mime
    with file_path.open("rb") as fh:
        response = requests.post(endpoint, headers=headers, data=fh, timeout=120)
    response.raise_for_status()
    return response.json()


def ensure_wc_categories(settings: dict[str, str], category_text: str) -> list[dict[str, int]]:
    categories = [item.strip() for item in re.split(r"[,;|]", category_text or "") if item.strip()]
    payload = []
    endpoint = settings["wc_url"].rstrip("/") + "/wp-json/wc/v3/products/categories"
    for name in categories:
        if name.isdigit():
            payload.append({"id": int(name)})
            continue
        search = requests.get(
            endpoint,
            auth=(settings["wc_key"], settings["wc_secret"]),
            params={"search": name, "per_page": 20},
            timeout=60,
        )
        search.raise_for_status()
        matches = search.json()
        exact = next((item for item in matches if normalize_key(item.get("name", "")) == normalize_key(name)), None)
        if exact:
            payload.append({"id": exact["id"]})
            continue
        created = requests.post(
            endpoint,
            auth=(settings["wc_key"], settings["wc_secret"]),
            json={"name": name},
            timeout=60,
        )
        created.raise_for_status()
        payload.append({"id": created.json()["id"]})
    return payload


def apply_product_overrides(preview: dict[str, Any], overrides: dict[str, Any] | None) -> dict[str, Any]:
    if not overrides:
        return preview
    result = dict(preview)
    for key in ["title", "description", "price", "category"]:
        value = str(overrides.get(key, "")).strip()
        if value:
            result[key] = value
    tags = overrides.get("tags")
    if isinstance(tags, list):
        result["tags"] = [str(tag).strip() for tag in tags if str(tag).strip()]
    elif isinstance(tags, str) and tags.strip():
        result["tags"] = [tag.strip() for tag in re.split(r"[,;|]", tags) if tag.strip()]
    return result


def local_generate(field: str, product: dict[str, Any]) -> str:
    title = str(product.get("title") or "").strip() or "Sewing Pattern"
    description = str(product.get("description") or "").strip()
    category = str(product.get("category") or "Sewing Patterns").strip()
    tags = [tag.strip() for tag in re.split(r"[,;|]", str(product.get("tags") or "")) if tag.strip()]
    clean_title = re.sub(r"\s+", " ", title)
    if field == "title":
        base = clean_title.split("|")[0].strip()
        if "sewing pattern" not in base.lower():
            base = f"{base} Sewing Pattern"
        return f"{base} | PDF Pattern | Instant Download"
    if field == "tags":
        generated = tags + [
            "PDF sewing pattern",
            "instant download",
            "A4 US Letter",
            "A0 pattern",
            "layered pattern",
            "beginner friendly",
            category,
        ]
        unique = []
        for tag in generated:
            if tag and normalize_key(tag) not in {normalize_key(item) for item in unique}:
                unique.append(tag)
        return ", ".join(unique[:12])
    summary = description or f"Create a beautiful handmade garment with this {clean_title}."
    return (
        f"{clean_title}\n\n"
        f"{summary}\n\n"
        "This digital sewing pattern includes printable files for home printing and copy-shop printing, "
        "plus clear instructions to help you sew your garment with confidence.\n\n"
        "Included:\n"
        "- PDF sewing pattern\n"
        "- A4/US Letter print-at-home file\n"
        "- A0 copy-shop file\n"
        "- Step-by-step sewing guide\n"
        "- Instant digital download"
    )


def create_wc_product(settings: dict[str, str], preview: dict[str, Any], folder_path: Path) -> dict[str, Any]:
    wc_url = settings["wc_url"].rstrip("/")
    media_files = []
    image_payload = []
    for image_url in preview["images"]:
        image_path = (CANDIDATE_DIR if "candidates" in image_url else IMAGE_DIR) / Path(image_url).name
        media = upload_media(settings["wc_url"], settings["wp_username"], settings["wp_app_password"], image_path)
        image_payload.append({"id": media["id"]})
    for pdf_name in preview["pdfs"]:
        media = upload_media(settings["wc_url"], settings["wp_username"], settings["wp_app_password"], folder_path / pdf_name)
        media_files.append({"name": pdf_name, "file": media["source_url"]})
    payload = {
        "name": preview["title"],
        "type": "simple",
        "status": settings.get("status", "draft"),
        "virtual": True,
        "downloadable": True,
        "regular_price": str(preview.get("price") or settings.get("price", "6.99")),
        "description": preview["description"],
        "short_description": preview["description"][:450],
        "tags": [{"name": tag} for tag in preview["tags"]],
        "images": image_payload,
        "downloads": media_files,
    }
    categories = ensure_wc_categories(settings, str(preview.get("category", "")))
    if categories:
        payload["categories"] = categories
    response = requests.post(
        wc_url + "/wp-json/wc/v3/products",
        auth=(settings["wc_key"], settings["wc_secret"]),
        json=payload,
        timeout=120,
    )
    response.raise_for_status()
    return response.json()


def push(job_id: str, event: str, data: Any) -> None:
    jobs[job_id].put({"event": event, "data": data})


def run_upload(job_id: str, only_one: bool, settings: dict[str, str]) -> None:
    try:
        products = scan_folders()
        try:
            rows = load_sheet(settings.get("sheet_url") or DEFAULT_SHEET_URL)
        except Exception as exc:
            if settings.get("dry_run") != "true":
                raise
            rows = []
            push(job_id, "log", f"Sheet warning: {exc}")
        start_index = int(settings.get("index") or 0) if only_one else 0
        selected_images = settings.get("selected_images") or []
        work_items = products[start_index : start_index + 1] if only_one else products
        for offset, product in enumerate(work_items):
            index = start_index + offset if only_one else offset
            push(job_id, "log", f"Preparing {product.folder}")
            row = match_sheet_row(product, rows, index)
            preview = product_preview(product, row, selected_images=selected_images if only_one else None)
            if only_one:
                preview = apply_product_overrides(preview, settings.get("product"))
            if settings.get("dry_run") == "true":
                push(job_id, "product", preview)
                push(job_id, "log", "Dry run complete. No WooCommerce upload was made.")
                continue
            created = create_wc_product(settings, preview, Path(product.path))
            push(job_id, "product", {"title": preview["title"], "woocommerce_id": created.get("id"), "permalink": created.get("permalink")})
            push(job_id, "log", f"Created WooCommerce product #{created.get('id')}: {preview['title']}")
        push(job_id, "done", "Finished")
    except Exception as exc:
        push(job_id, "error", str(exc))
    finally:
        jobs[job_id].put(None)


@app.route("/")
def index() -> str:
    return render_template("index.html", config=config_status())


@app.route("/output/images/<path:name>")
def output_image(name: str) -> Response:
    return send_from_directory(IMAGE_DIR, name)


@app.route("/output/candidates/<path:name>")
def output_candidate(name: str) -> Response:
    return send_from_directory(CANDIDATE_DIR, name)


@app.get("/api/scan")
def api_scan() -> Response:
    return jsonify([asdict(item) for item in scan_folders()])


@app.post("/api/preview")
def api_preview() -> Response:
    data = request.get_json(force=True)
    config = load_config()
    products = scan_folders()
    sheet_warning = None
    try:
        rows = load_sheet(config.get("sheet_url") or DEFAULT_SHEET_URL)
    except Exception as exc:
        rows = []
        sheet_warning = f"Sheet warning: {exc}"
    index = int(data.get("index", 0))
    product = products[index]
    return jsonify(product_preview(product, match_sheet_row(product, rows, index), [sheet_warning] if sheet_warning else None))


@app.post("/api/start")
def api_start() -> Response:
    data = request.get_json(force=True)
    settings = load_config()
    settings["dry_run"] = "true" if data.get("dry_run", False) else "false"
    settings["index"] = str(int(data.get("index", 0)))
    settings["selected_images"] = data.get("selected_images") or []
    settings["product"] = data.get("product") or {}
    job_id = str(int(time.time() * 1000))
    jobs[job_id] = queue.Queue()
    thread = threading.Thread(target=run_upload, args=(job_id, bool(data.get("only_one", True)), settings), daemon=True)
    thread.start()
    return jsonify({"job_id": job_id})


@app.post("/api/ai-generate")
def api_ai_generate() -> Response:
    data = request.get_json(force=True)
    config = load_config()
    field = data.get("field", "")
    product = data.get("product") or {}
    if field not in {"title", "description", "tags"}:
        return jsonify({"error": "Invalid field."}), 400
    api_key = config.get("openrouter_api_key")
    if not api_key:
        return jsonify({"text": local_generate(field, product), "source": "local"})
    instructions = {
        "title": "Write one SEO-friendly WooCommerce product title. Return only the title.",
        "description": "Write a complete WooCommerce product description for a digital sewing pattern. Return polished description text only.",
        "tags": "Write 12 concise SEO tags for this sewing pattern. Return comma-separated tags only.",
    }
    prompt = (
        f"{instructions[field]}\n\n"
        f"Current title: {product.get('title', '')}\n"
        f"Current description: {product.get('description', '')}\n"
        f"Current tags: {product.get('tags', '')}\n"
        f"Category: {product.get('category', '')}\n"
    )
    try:
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": config.get("wc_url", "http://127.0.0.1:5050"),
                "X-Title": "WooCommerce Pattern Importer",
            },
            json={
                "model": config.get("openrouter_model", "openai/gpt-4o-mini"),
                "messages": [
                    {"role": "system", "content": "You write clear, sales-ready product copy for sewing pattern downloads."},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.7,
            },
            timeout=120,
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"].strip()
    except Exception as exc:
        detail = ""
        if "response" in locals():
            try:
                detail = response.text[:500]
            except Exception:
                detail = ""
        fallback = local_generate(field, product)
        return jsonify({"text": fallback, "source": "local", "warning": f"OpenRouter failed: {exc}. {detail}".strip()})
    return jsonify({"text": content, "source": "openrouter"})


@app.get("/api/events/<job_id>")
def api_events(job_id: str) -> Response:
    def stream():
        q = jobs.get(job_id)
        if q is None:
            yield "event: error\ndata: \"Unknown job\"\n\n"
            return
        while True:
            item = q.get()
            if item is None:
                break
            yield f"event: {item['event']}\ndata: {json.dumps(item['data'])}\n\n"

    return Response(stream(), mimetype="text/event-stream")


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5050, debug=True, threaded=True)
