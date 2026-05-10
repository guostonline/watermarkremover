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
from flask import Blueprint, Flask, Response, jsonify, render_template, request, send_from_directory
from google.oauth2 import service_account
from googleapiclient.discovery import build
from PIL import Image, ImageDraw, ImageFilter, ImageStat


ROOT = Path(__file__).resolve().parent
EXPORT_DIR = ROOT / "_wc_importer_output"
IMAGE_DIR = EXPORT_DIR / "images"
CANDIDATE_DIR = EXPORT_DIR / "candidates"
IMAGE_DIR.mkdir(parents=True, exist_ok=True)
CANDIDATE_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_SHEET_URL = "https://docs.google.com/spreadsheets/d/1L6bni_tF_q4qplJeZWLZ59e6qZ_Ds0XlPVkLCRXZglo/edit?gid=266948403#gid=266948403"
CONFIG_PATH = ROOT / "config.json"
SHEET_CACHE_PATH = ROOT / "sheet_cache.json"

woo_bp = Blueprint("woo", __name__, template_folder="templates")
jobs: dict[str, queue.Queue] = {}


def load_config() -> dict[str, str]:
    defaults = {
        "sheet_url": DEFAULT_SHEET_URL,
        "root_folder": "",
        "wc_url": "",
        "wc_key": "",
        "wc_secret": "",
        "wp_username": "",
        "wp_app_password": "",
        "price": "6.99",
        "sale_percent": "70",
        "status": "draft",
        "default_category": "",
        "openrouter_api_key": "",
        "openrouter_model": "google/gemini-2.5-flash-preview",
        "google_service_account_file": "",
        "google_service_account_json": "",
        "sheet_name": "",
        "sheet_status_column": "Statut WooCommerce",
        "appwrite_endpoint": "https://cloud.appwrite.io/v1",
        "appwrite_project_id": "",
        "appwrite_api_key": "",
        "appwrite_db_id": "patternlistings",
        "appwrite_collection_id": "listings",
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


def get_root_folder() -> Path:
    cfg_path = load_config().get("root_folder", "").strip()
    if cfg_path and Path(cfg_path).is_dir():
        return Path(cfg_path)
    return ROOT


def scan_folders() -> list[ProductFolder]:
    products: list[ProductFolder] = []
    scan_root = get_root_folder()
    for folder in sorted([p for p in scan_root.iterdir() if p.is_dir() and not p.name.startswith("_")], key=natural_key):
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
    url = f"https://docs.google.com/spreadsheets/d/{match.group(1)}/export?format=csv"
    gid_match = re.search(r"gid=(\d+)", sheet_url)
    if gid_match:
        url += f"&gid={gid_match.group(1)}"
    return url


def sheet_csv_candidate_urls(sheet_url: str) -> list[str]:
    """Build multiple CSV endpoints to survive flaky Google redirect hosts."""
    match = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", sheet_url)
    gid_match = re.search(r"gid=(\d+)", sheet_url)
    gid = gid_match.group(1) if gid_match else None
    if not match:
        return [sheet_url]
    sid = match.group(1)
    urls = [
        f"https://docs.google.com/spreadsheets/d/{sid}/export?format=csv",
        f"https://docs.google.com/spreadsheets/d/{sid}/gviz/tq?tqx=out:csv",
        f"https://docs.google.com/spreadsheets/d/{sid}/pub?output=csv",
    ]
    if gid:
        urls = [u + ("&" if "?" in u else "?") + f"gid={gid}" for u in urls]
    # Preserve old behavior as an extra fallback at the end.
    primary = sheet_csv_url(sheet_url)
    if primary not in urls:
        urls.append(primary)
    return urls


def normalize_key(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "", ascii_value.lower())


def load_sheet(sheet_url: str) -> list[dict[str, str]]:
    urls = sheet_csv_candidate_urls(sheet_url)
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0"})
    last_error = None
    for url in urls:
        for attempt in range(3):
            try:
                response = session.get(url, timeout=30, allow_redirects=True)
                response.raise_for_status()
                # Google sometimes returns an HTML error page with 200 – detect it
                content_type = response.headers.get("content-type", "")
                if "text/html" in content_type and b"<!DOCTYPE" in response.content[:50]:
                    raise RuntimeError("Google returned an HTML page instead of CSV — check that the sheet is publicly shared.")
                text = response.content.decode("utf-8-sig", errors="replace")
                rows = list(csv.DictReader(io.StringIO(text)))
                if not rows:
                    raise RuntimeError("Sheet returned 0 rows — it may not be publicly shared.")
                return rows
            except Exception as exc:
                last_error = exc
                if attempt < 2:
                    time.sleep(2)
    raise RuntimeError(f"Could not read Google Sheet: {last_error}")


def save_sheet_cache(rows: list[dict[str, str]]) -> None:
    payload = {"fetched_at": time.time(), "count": len(rows), "rows": rows}
    with SHEET_CACHE_PATH.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)


def load_sheet_cached(max_age_seconds: int = 21600) -> list[dict[str, str]]:
    """Return cached sheet rows.  Falls back to live fetch if cache is missing or stale."""
    if SHEET_CACHE_PATH.exists():
        try:
            with SHEET_CACHE_PATH.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
            age = time.time() - float(data.get("fetched_at", 0))
            if age < max_age_seconds:
                return data.get("rows", [])
        except Exception:
            pass
    # cache miss – try live fetch silently
    try:
        config = load_config()
        rows = load_sheet(config.get("sheet_url") or DEFAULT_SHEET_URL)
        save_sheet_cache(rows)
        return rows
    except Exception:
        # return stale cache rather than nothing
        if SHEET_CACHE_PATH.exists():
            try:
                with SHEET_CACHE_PATH.open("r", encoding="utf-8") as fh:
                    return json.load(fh).get("rows", [])
            except Exception:
                pass
    return []


def sheet_cache_meta() -> dict[str, Any]:
    if not SHEET_CACHE_PATH.exists():
        return {"synced": False, "count": 0, "age_seconds": None}
    try:
        with SHEET_CACHE_PATH.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        return {
            "synced": True,
            "count": data.get("count", 0),
            "age_seconds": int(time.time() - float(data.get("fetched_at", 0))),
            "fetched_at": data.get("fetched_at"),
        }
    except Exception:
        return {"synced": False, "count": 0, "age_seconds": None}


def row_to_dict(row: dict[str, str]) -> dict[str, str]:
    """Normalise a raw CSV row into a clean flat dict with consistent keys."""
    return {
        "number":                  pick_field(row, ["#", "num", "number"]),
        "nom_du_patron":           pick_field(row, ["Nom du Patron"]),
        "categorie":               pick_field(row, ["Catégorie"]),
        "sous_categorie":          pick_field(row, ["Sous-catégorie"]),
        "demande":                 pick_field(row, ["Demande"]),
        "concurrence":             pick_field(row, ["Concurrence"]),
        "unicite":                 pick_field(row, ["Unicité"]),
        "priorite":                pick_field(row, ["Priorité"]),
        "statut_etsy":             pick_field(row, ["Statut Etsy"]),
        "statut_woocommerce":      pick_field(row, ["Statut WooCommerce", "WooCommerce Status"]),
        "prix":                    pick_field(row, ["Prix (USD)", "price"]),
        "titre_etsy":              pick_field(row, ["Titre Etsy Suggéré"]),
        "tags":                    pick_field(row, ["Tags Principaux"]),
        "notes":                   pick_field(row, ["Notes"]),
        "dossier_source":          pick_field(row, ["Dossier Source"]),
        "indiepattern_match":      pick_field(row, ["✅ Match"]),
        "indiepattern_titre":      pick_field(row, ["IndiePattern Titre"]),
        "indiepattern_url":        pick_field(row, ["IndiePattern URL"]),
        "indiepattern_description":pick_field(row, ["IndiePattern Description"]),
        "indiepattern_keywords":   pick_field(row, ["IndiePattern Keywords"]),
    }


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
        folder_name = pick_field(row, ["Dossier Source", "Ton Pattern (Dossier)", "folder", "dossier", "pattern"])
        folder_key = normalize_key(folder_name)
        if folder_key and (product_name == folder_key or product_name in folder_key or folder_key in product_name):
            return row
    for row in rows:
        title = pick_field(row, ["Titre Etsy Suggéré", "IndiePattern Titre", "Titre IndiePattern", "title", "name", "product title"])
        if title and product_name in normalize_key(title):
            return row
    for row in rows:
        row_id = pick_field(row, ["id", "number", "num", "#", "product number"])
        sheet_number = product.number + 1 if product.number is not None else None
        if row_id and sheet_number is not None and re.search(rf"\b{sheet_number}\b", row_id):
            return row
    return rows[index] if index < len(rows) else {}


def candidate_sheet_row_indices(product: ProductFolder, rows: list[dict[str, str]], index: int) -> list[int]:
    if not rows:
        return []
    candidates: list[int] = []
    product_name = normalize_key(product.clean_name)
    for row_idx, row in enumerate(rows):
        folder_name = pick_field(row, ["Dossier Source", "Ton Pattern (Dossier)", "folder", "dossier", "pattern"])
        folder_key = normalize_key(folder_name)
        if folder_key and (product_name == folder_key or product_name in folder_key or folder_key in product_name):
            candidates.append(row_idx)
    for row_idx, row in enumerate(rows):
        title = pick_field(row, ["Titre Etsy Suggéré", "IndiePattern Titre", "Titre IndiePattern", "title", "name", "product title"])
        if title and product_name in normalize_key(title):
            candidates.append(row_idx)
    for row_idx, row in enumerate(rows):
        row_id = pick_field(row, ["id", "number", "num", "#", "product number"])
        sheet_number = product.number + 1 if product.number is not None else None
        if row_id and sheet_number is not None and re.search(rf"\b{sheet_number}\b", row_id):
            candidates.append(row_idx)
    unique: list[int] = []
    seen: set[int] = set()
    for item in candidates:
        if item not in seen:
            seen.add(item)
            unique.append(item)
    return unique


def build_unique_sheet_mapping(products: list[ProductFolder], rows: list[dict[str, str]]) -> list[int | None]:
    used: set[int] = set()
    mapping: list[int | None] = []
    for index, product in enumerate(products):
        picked: int | None = None
        for row_idx in candidate_sheet_row_indices(product, rows, index):
            if row_idx not in used:
                picked = row_idx
                break
        if picked is not None:
            used.add(picked)
        mapping.append(picked)
    return mapping


def match_sheet_row_index(product: ProductFolder, rows: list[dict[str, str]], index: int) -> int | None:
    if not rows:
        return None
    product_name = normalize_key(product.clean_name)
    for row_idx, row in enumerate(rows):
        folder_name = pick_field(row, ["Dossier Source", "Ton Pattern (Dossier)", "folder", "dossier", "pattern"])
        folder_key = normalize_key(folder_name)
        if folder_key and (product_name == folder_key or product_name in folder_key or folder_key in product_name):
            return row_idx
    for row_idx, row in enumerate(rows):
        title = pick_field(row, ["Titre Etsy Suggéré", "IndiePattern Titre", "Titre IndiePattern", "title", "name", "product title"])
        if title and product_name in normalize_key(title):
            return row_idx
    for row_idx, row in enumerate(rows):
        row_id = pick_field(row, ["id", "number", "num", "#", "product number"])
        sheet_number = product.number + 1 if product.number is not None else None
        if row_id and sheet_number is not None and re.search(rf"\b{sheet_number}\b", row_id):
            return row_idx
    return index if 0 <= index < len(rows) else None


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
        image = remove_indiepattern_watermark(image)
        image.save(out, "JPEG", quality=92, optimize=True)


def remove_indiepattern_watermark(image: Image.Image) -> Image.Image:
    """Hide likely corner watermark by replacing corner patch with nearby texture."""
    working = image.copy().convert("RGB")
    width, height = working.size
    patch_w = max(120, int(width * 0.30))
    patch_h = max(80, int(height * 0.15))

    # Bottom-right and bottom-left cover the common watermark positions.
    target_boxes = [
        (max(0, width - patch_w), max(0, height - patch_h), width, height),
        (0, max(0, height - patch_h), min(width, patch_w), height),
    ]
    for x0, y0, x1, y1 in target_boxes:
        region_w = x1 - x0
        region_h = y1 - y0
        if region_w < 10 or region_h < 10:
            continue

        # Sample nearby area from the inside of the image.
        sample_x0 = min(max(0, x0 - region_w), max(0, width - region_w))
        sample_y0 = min(max(0, y0 - region_h), max(0, height - region_h))
        sample_x1 = sample_x0 + region_w
        sample_y1 = sample_y0 + region_h
        sample = working.crop((sample_x0, sample_y0, sample_x1, sample_y1)).filter(ImageFilter.GaussianBlur(1.4))

        mask = Image.new("L", (region_w, region_h), 0)
        draw = ImageDraw.Draw(mask)
        draw.rounded_rectangle((0, 0, region_w - 1, region_h - 1), radius=22, fill=230)
        mask = mask.filter(ImageFilter.GaussianBlur(5.5))
        working.paste(sample, (x0, y0), mask)

    return working


def is_model_photo(image_bytes: bytes, ext: str, width: int, height: int) -> bool:
    """Return True only when the image looks like a fashion model photo.

    Rejects:
    - Non-JPEG images (pattern pieces are almost always PNG/BMP).
    - Landscape images wider than 1.4× their height (pattern sheets).
    - Very bright images (mean > 185) — diagrams on white paper.
    - Achromatic images (channel spread < 10) — line-art / grayscale diagrams.
    - Low-texture images (stddev < 18) — flat fills or nearly blank pages.
    """
    if ext not in ("jpg", "jpeg"):
        return False
    if width > 0 and height > 0 and width > height * 1.4:
        return False
    try:
        with Image.open(io.BytesIO(image_bytes)) as img:
            sample = img.convert("RGB").resize((80, 80))
            stats = ImageStat.Stat(sample)
            mean = sum(stats.mean) / 3
            stddev = sum(stats.stddev) / 3
            r_mean, g_mean, b_mean = stats.mean
            channel_spread = max(r_mean, g_mean, b_mean) - min(r_mean, g_mean, b_mean)
    except Exception:
        return False
    if mean > 185:
        return False
    if channel_spread < 10:
        return False
    if stddev < 18:
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
                ext = (info.get("ext") or "").lower()
                if width < 450 or height < 450 or width * height < 250_000:
                    continue
                model_like = is_model_photo(image_bytes, ext, width, height)
                digest = hashlib.sha1(image_bytes).hexdigest()
                if digest in seen:
                    continue
                seen.add(digest)
                early_page_bonus = max(0, 80_000 - page_index * 10_000)
                portrait_bonus = 120_000 if height > width else 0
                model_bonus = 2_000_000 if model_like else 0
                score = (width * height) + len(image_bytes) + early_page_bonus + portrait_bonus + model_bonus
                candidates.append(
                    {
                        "pdf": pdf,
                        "page": page_index,
                        "image_index": image_index,
                        "width": width,
                        "height": height,
                        "is_model": model_like,
                        "bytes": image_bytes,
                        "score": score,
                    }
                )
        doc.close()
    candidates.sort(key=lambda item: (item.get("is_model", False), item["score"]), reverse=True)
    return candidates


def extract_model_images(folder: Path, force: bool = False) -> list[str]:
    safe = re.sub(r"[^a-zA-Z0-9_-]+", "-", folder.name).strip("-")
    existing = [IMAGE_DIR / f"{safe}-model-1.jpg", IMAGE_DIR / f"{safe}-model-2.jpg"]
    if all(p.exists() for p in existing) and not force:
        return [f"/woo/output/images/{p.name}" for p in existing]

    embedded = embedded_pdf_images(folder)
    preferred = [item for item in embedded if item.get("is_model")]
    if not preferred:
        preferred = embedded
    urls = []
    for out_index, candidate in enumerate(preferred[:2], start=1):
        out = IMAGE_DIR / f"{safe}-model-{out_index}.jpg"
        save_embedded_image(candidate["bytes"], out)
        urls.append(f"/woo/output/images/{out.name}")
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
        save_embedded_image(pix.tobytes("png"), out)
        urls.append(f"/woo/output/images/{out.name}")
    doc.close()
    return urls


def extract_candidate_images(folder: Path, force: bool = False, limit: int = 0) -> list[dict[str, Any]]:
    safe = re.sub(r"[^a-zA-Z0-9_-]+", "-", folder.name).strip("-")
    candidates = embedded_pdf_images(folder)
    output: list[dict[str, Any]] = []
    selected = candidates if limit <= 0 else candidates[:limit]
    for out_index, candidate in enumerate(selected, start=1):
        out = CANDIDATE_DIR / f"{safe}-choice-{out_index}.jpg"
        if force or not out.exists():
            save_embedded_image(candidate["bytes"], out)
        output.append(
            {
                "url": f"/woo/output/candidates/{out.name}",
                "file": out.name,
                "pdf": candidate["pdf"].name,
                "page": candidate["page"] + 1,
                "width": candidate["width"],
                "height": candidate["height"],
                "is_model": bool(candidate.get("is_model")),
            }
        )
    return output


def product_preview(
    product: ProductFolder,
    row: dict[str, str],
    extra_warnings: list[str] | None = None,
    selected_images: list[str] | None = None,
) -> dict[str, Any]:
    title = pick_field(row, ["Titre Etsy Suggéré", "IndiePattern Titre", "Titre IndiePattern", "title", "name", "product title"]) or product.clean_name
    description = pick_field(row, ["IndiePattern Description", "Description Complète", "description complete", "description", "desc"])
    tags_text = pick_field(row, ["Tags Principaux", "IndiePattern Keywords", "Mots-clés Inclus", "mots cles inclus", "tags", "tag"])
    tags = [t.strip() for t in re.split(r"[,;|]", tags_text) if t.strip()]
    choices = extract_candidate_images(Path(product.path))
    images = selected_images or [choice["url"] for choice in choices[:2]] or extract_model_images(Path(product.path))
    return {
        "folder": product.folder,
        "number": product.number,
        "nom_du_patron": pick_field(row, ["Nom du Patron"]) or product.clean_name,
        "categorie": pick_field(row, ["Catégorie"]) or "",
        "sous_categorie": pick_field(row, ["Sous-catégorie"]) or "",
        "demande": pick_field(row, ["Demande"]) or "",
        "concurrence": pick_field(row, ["Concurrence"]) or "",
        "unicite": pick_field(row, ["Unicité"]) or "",
        "priorite": pick_field(row, ["Priorité"]) or "",
        "statut": pick_field(row, ["Statut Etsy"]) or "",
        "dossier_source": pick_field(row, ["Dossier Source"]) or "",
        "notes": pick_field(row, ["Notes"]) or "",
        "indiepattern_url": pick_field(row, ["IndiePattern URL"]) or "",
        "indiepattern_keywords": pick_field(row, ["IndiePattern Keywords"]) or "",
        "title": title,
        "description": description,
        "tags": tags,
        "price": pick_field(row, ["Prix (USD)", "price"]) or load_config().get("price", "6.99"),
        "category": pick_field(row, ["Catégorie", "Sous-catégorie", "category"]) or load_config().get("default_category", ""),
        "indiepattern_titre": pick_field(row, ["IndiePattern Titre"]) or "",
        "indiepattern_match": pick_field(row, ["✅ Match"]) or "",
        "images": images,
        "image_choices": choices,
        "pdfs": product.pdfs,
        "warnings": product.warnings + (extra_warnings or []),
    }


def auth_header(username: str, app_password: str) -> dict[str, str]:
    token = base64.b64encode(f"{username}:{app_password.replace(' ', '')}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def parse_sheet_id_gid(sheet_url: str) -> tuple[str | None, int | None]:
    id_match = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", sheet_url or "")
    gid_match = re.search(r"gid=(\d+)", sheet_url or "")
    sheet_id = id_match.group(1) if id_match else None
    gid = int(gid_match.group(1)) if gid_match else None
    return sheet_id, gid


def resolve_sheet_column_name(headers: list[str], preferred: list[str]) -> str | None:
    norm_headers = {normalize_key(h): h for h in headers if h}
    for candidate in preferred:
        match = norm_headers.get(normalize_key(candidate))
        if match:
            return match
    return None


def get_google_service_account_credentials(settings: dict[str, str]):
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    raw_json = str(settings.get("google_service_account_json") or "").strip()
    file_path = str(settings.get("google_service_account_file") or "").strip()
    if raw_json:
        info = json.loads(raw_json)
        return service_account.Credentials.from_service_account_info(info, scopes=scopes)
    if file_path:
        return service_account.Credentials.from_service_account_file(file_path, scopes=scopes)
    return None


def update_sheet_status_cache(rows: list[dict[str, str]], row_idx: int, status_value: str, column_name: str) -> None:
    if row_idx < 0 or row_idx >= len(rows):
        return
    row = rows[row_idx]
    target = resolve_sheet_column_name(list(row.keys()), [column_name, "Statut WooCommerce", "WooCommerce Status", "Statut Etsy"])
    if not target:
        target = column_name
    row[target] = status_value
    save_sheet_cache(rows)


def update_google_sheet_status(settings: dict[str, str], product: ProductFolder, row_idx: int, rows: list[dict[str, str]], status_value: str = "Publié") -> tuple[bool, str]:
    if row_idx < 0 or row_idx >= len(rows):
        return False, "No sheet row match found"
    row = rows[row_idx]
    preferred_column = str(settings.get("sheet_status_column") or "Statut WooCommerce").strip() or "Statut WooCommerce"
    column_name = resolve_sheet_column_name(list(row.keys()), [preferred_column, "Statut WooCommerce", "WooCommerce Status", "Statut Etsy"])
    if not column_name:
        return False, "Status column not found in sheet headers"

    update_sheet_status_cache(rows, row_idx, status_value, column_name)

    sheet_url = settings.get("sheet_url") or DEFAULT_SHEET_URL
    spreadsheet_id, sheet_gid = parse_sheet_id_gid(sheet_url)
    if not spreadsheet_id:
        return False, "Could not parse spreadsheet ID"
    credentials = get_google_service_account_credentials(settings)
    if credentials is None:
        return False, "Google credentials not configured (set google_service_account_file or google_service_account_json)"

    service = build("sheets", "v4", credentials=credentials, cache_discovery=False)
    sheet_name = str(settings.get("sheet_name") or "").strip()
    meta = service.spreadsheets().get(spreadsheetId=spreadsheet_id, fields="sheets(properties(sheetId,index,title))").execute()
    sheets = meta.get("sheets") or []

    if sheet_name:
        by_name = next((s for s in sheets if str(s.get("properties", {}).get("title", "")).strip() == sheet_name), None)
        if not by_name:
            return False, f"Worksheet '{sheet_name}' not found"
        sheet_gid = int(by_name.get("properties", {}).get("sheetId", 0))

    if sheet_gid is None:
        if not sheets:
            return False, "No worksheet found in spreadsheet"
        sheet_gid = int(sheets[0].get("properties", {}).get("sheetId", 0))

    headers = list(row.keys())
    col_idx = headers.index(column_name)
    row_number = row_idx + 2  # +1 for 1-based indexing, +1 for header row
    request_body = {
        "requests": [
            {
                "updateCells": {
                    "start": {
                        "sheetId": int(sheet_gid),
                        "rowIndex": row_number - 1,
                        "columnIndex": col_idx,
                    },
                    "rows": [
                        {
                            "values": [
                                {
                                    "userEnteredValue": {"stringValue": status_value}
                                }
                            ]
                        }
                    ],
                    "fields": "userEnteredValue",
                }
            }
        ]
    }
    service.spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body=request_body).execute()
    return True, f"Updated sheet row {row_number} ({column_name}) to '{status_value}'"


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
    for key in ["title", "description", "short_description", "price", "category"]:
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
    if field == "short_description":
        price = str(product.get("price") or "").strip()
        price_line = f" for just ${price}" if price else " at a friendly price"
        return (
            f"Sew your dream look with this beautiful {clean_title} PDF pattern{price_line}. "
            "Instant download, clear illustrated steps, and professional-looking results make this the perfect pattern to start today."
        )
    summary = description or f"Create a beautiful, one-of-a-kind handmade garment with this {clean_title}."
    return (
        f"Discover the joy of sewing your own {clean_title} — a beautifully designed PDF pattern "
        f"that will guide you from cutting table to finished garment with confidence and ease.\n\n"
        f"{summary}\n\n"
        f"Whether you are a weekend sewer or an experienced maker, this pattern gives you everything "
        f"you need to create a garment you will be proud to wear. The clear, illustrated instructions "
        f"walk you through every step, so you spend less time guessing and more time sewing.\n\n"
        "WHAT'S INCLUDED:\n"
        "- A0 copy-shop PDF (print at your local print shop for fast, tape-free assembly)\n"
        "- A4 / US Letter home-print PDF (print at home, easy-to-assemble pages)\n"
        "- Step-by-step illustrated sewing guide\n"
        "- Size chart and ease information\n"
        "- Fabric & notions recommendations\n"
        "- Instant digital download — no waiting, no shipping!\n\n"
        "WHY YOU WILL LOVE IT:\n"
        "- Professional-quality pattern at a fraction of boutique prices\n"
        "- Layered PDF so you can print only the sizes you need\n"
        "- Beginner-friendly instructions with clear diagrams\n"
        "- Print as many copies as you like for personal use\n"
        "- Compatible with all home printers — US Letter or A4\n\n"
        "FABRIC SUGGESTIONS:\n"
        "This pattern works beautifully in woven cottons, linen blends, chambray, rayon challis, "
        "and lightweight denim. For a drapey look, try viscose or Tencel. "
        "Check the pattern guide for exact yardage and stretch requirements.\n\n"
        "Add this pattern to your cart today and start creating something beautiful this weekend!"
    )


def create_wc_product(settings: dict[str, str], preview: dict[str, Any], folder_path: Path) -> dict[str, Any]:
    def to_amount(value: Any, fallback: float) -> float:
        try:
            amount = float(str(value).replace(",", ".").strip())
            if amount > 0:
                return amount
        except Exception:
            pass
        return fallback

    def money_text(value: float) -> str:
        text = f"{value:.2f}"
        return text.rstrip("0").rstrip(".") if "." in text else text

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
    sale_price = to_amount(preview.get("price"), to_amount(settings.get("price", "6.99"), 6.99))
    sale_percent = to_amount(settings.get("sale_percent", "70"), 70.0)
    if sale_percent <= 0 or sale_percent >= 100:
        regular_price = sale_price
    else:
        regular_price = sale_price / (1 - (sale_percent / 100.0))
    if regular_price < sale_price:
        regular_price = sale_price

    payload = {
        "name": preview["title"],
        "type": "simple",
        "status": str(preview.get("status") or settings.get("status", "draft")).strip() or "draft",
        "virtual": True,
        "downloadable": True,
        "regular_price": money_text(regular_price),
        "sale_price": money_text(sale_price),
        "description": preview["description"],
        "short_description": str(preview.get("short_description") or "").strip() or preview["description"][:450],
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


@woo_bp.route("/")
def index() -> str:
    return render_template("woo_uploader.html", config=config_status(), woo_base="/woo")


@woo_bp.route("/listings")
def listings_page() -> str:
    return render_template("woo_uploader.html", config=config_status(), woo_base="/woo")


@woo_bp.route("/listing-generator")
def listing_generator_page() -> str:
    return render_template("woo_uploader.html", config=config_status(), woo_base="/woo")


@woo_bp.route("/sync")
def sync_page() -> str:
    return render_template("woo_uploader.html", config=config_status(), woo_base="/woo")


@woo_bp.route("/settings")
def settings_page() -> str:
    return render_template("woo_uploader.html", config=config_status(), woo_base="/woo")


@woo_bp.route("/output/images/<path:name>")
def output_image(name: str) -> Response:
    return send_from_directory(IMAGE_DIR, name)


@woo_bp.route("/output/candidates/<path:name>")
def output_candidate(name: str) -> Response:
    return send_from_directory(CANDIDATE_DIR, name)


@woo_bp.get("/api/ping")
def api_ping() -> Response:
    return jsonify({"ok": True})


@woo_bp.post("/api/save-settings")
def api_save_settings() -> Response:
    data = request.json or {}
    cfg: dict = {}
    if CONFIG_PATH.exists():
        with CONFIG_PATH.open("r", encoding="utf-8") as fh:
            cfg = json.load(fh)
    for key in ("root_folder", "sheet_url", "wc_url", "wc_key", "wc_secret",
                "wp_username", "wp_app_password", "price", "status",
                "default_category", "openrouter_api_key", "openrouter_model"):
        if key in data:
            cfg[key] = data[key]
    with CONFIG_PATH.open("w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2, ensure_ascii=False)
    return jsonify({"ok": True, "root_folder": cfg.get("root_folder", "")})


@woo_bp.get("/api/settings")
def api_get_settings() -> Response:
    cfg = load_config()
    return jsonify({"root_folder": cfg.get("root_folder", ""), "scan_root": str(get_root_folder())})


@woo_bp.get("/api/folders-enriched")
def api_folders_enriched() -> Response:
    products = scan_folders()
    sheet_rows = load_sheet_cached()
    row_mapping = build_unique_sheet_mapping(products, sheet_rows)
    result = []
    for idx, product in enumerate(products):
        mapped_idx = row_mapping[idx] if idx < len(row_mapping) else None
        matched_row = sheet_rows[mapped_idx] if mapped_idx is not None and 0 <= mapped_idx < len(sheet_rows) else {}
        sheet = row_to_dict(matched_row) if matched_row else {}
        result.append({
            "index":       idx,
            "folder":      product.folder,
            "clean_name":  product.clean_name,
            "number":      product.number,
            "pdf_count":   len(product.pdfs),
            "warnings":    product.warnings,
            "sheet_matched": bool(matched_row),
            "sheet_row_index": mapped_idx,
            "categorie":   sheet.get("categorie", ""),
            "sous_categorie": sheet.get("sous_categorie", ""),
            "priorite":    sheet.get("priorite", ""),
            "statut_etsy": sheet.get("statut_etsy", ""),
            "statut_woocommerce": sheet.get("statut_woocommerce", ""),
            "demande":     sheet.get("demande", ""),
            "concurrence": sheet.get("concurrence", ""),
            "unicite":     sheet.get("unicite", ""),
            "indiepattern_match": sheet.get("indiepattern_match", ""),
            "prix":        sheet.get("prix", ""),
            "notes":       sheet.get("notes", ""),
        })
    return jsonify(result)


@woo_bp.get("/api/scan")
def api_scan() -> Response:
    return jsonify([asdict(item) for item in scan_folders()])


@woo_bp.get("/api/listings")
def api_listings() -> Response:
    config = load_config()
    products = scan_folders()
    sheet_warning = None
    try:
        rows = load_sheet(config.get("sheet_url") or DEFAULT_SHEET_URL)
    except Exception as exc:
        rows = []
        sheet_warning = str(exc)
    listings = []
    for index, product in enumerate(products):
        row = match_sheet_row(product, rows, index)
        entry: dict[str, Any] = {
            "index": index,
            "folder": product.folder,
            "number": product.number,
            "clean_name": product.clean_name,
            "pdfs": product.pdfs,
            "warnings": product.warnings,
            "matched": bool(row),
            "nom_du_patron": pick_field(row, ["Nom du Patron"]) if row else "",
            "categorie": pick_field(row, ["Catégorie"]) if row else "",
            "sous_categorie": pick_field(row, ["Sous-catégorie"]) if row else "",
            "demande": pick_field(row, ["Demande"]) if row else "",
            "concurrence": pick_field(row, ["Concurrence"]) if row else "",
            "unicite": pick_field(row, ["Unicité"]) if row else "",
            "priorite": pick_field(row, ["Priorité"]) if row else "",
            "statut": pick_field(row, ["Statut Etsy"]) if row else "",
            "statut_woocommerce": pick_field(row, ["Statut WooCommerce", "WooCommerce Status"]) if row else "",
            "prix": pick_field(row, ["Prix (USD)", "price"]) if row else "",
            "titre_etsy": pick_field(row, ["Titre Etsy Suggéré"]) if row else "",
            "tags": pick_field(row, ["Tags Principaux"]) if row else "",
            "notes": pick_field(row, ["Notes"]) if row else "",
            "dossier_source": pick_field(row, ["Dossier Source"]) if row else "",
            "indiepattern_match": pick_field(row, ["✅ Match"]) if row else "",
            "indiepattern_titre": pick_field(row, ["IndiePattern Titre"]) if row else "",
            "indiepattern_url": pick_field(row, ["IndiePattern URL"]) if row else "",
            "indiepattern_description": pick_field(row, ["IndiePattern Description"]) if row else "",
            "indiepattern_keywords": pick_field(row, ["IndiePattern Keywords"]) if row else "",
        }
        listings.append(entry)
    return jsonify({"listings": listings, "warning": sheet_warning})


def run_appwrite_sync(job_id: str, settings: dict[str, str]) -> None:
    try:
        endpoint = settings["appwrite_endpoint"]
        project_id = settings["appwrite_project_id"]
        api_key = settings["appwrite_api_key"]
        db_id = settings.get("appwrite_db_id", "patternlistings")
        collection_id = settings.get("appwrite_collection_id", "listings")
        
        headers = {
            "Content-Type": "application/json",
            "X-Appwrite-Key": api_key,
            "X-Appwrite-Project": project_id,
        }
        
        products = scan_folders()
        rows = load_sheet(settings.get("sheet_url") or DEFAULT_SHEET_URL)
        
        ok = 0
        fail = 0
        errors = []
        
        for index, product in enumerate(products):
            row = match_sheet_row(product, rows, index)
            
            doc = {
                "num": product.number or index + 1,
                "folder_name": product.folder,
                "nom_du_patron": pick_field(row, ["Nom du Patron"]) or product.clean_name,
                "categorie": pick_field(row, ["Catégorie"]) or "",
                "sous_categorie": pick_field(row, ["Sous-catégorie"]) or "",
                "demande": pick_field(row, ["Demande"]) or "",
                "concurrence": pick_field(row, ["Concurrence"]) or "",
                "unicite": pick_field(row, ["Unicité"]) or "",
                "priorite": pick_field(row, ["Priorité"]) or "",
                "statut": pick_field(row, ["Statut Etsy"]) or "",
                "prix": pick_field(row, ["Prix (USD)"]) or settings.get("price", "6.99"),
                "titre_etsy": pick_field(row, ["Titre Etsy Suggéré"]) or "",
                "tags": pick_field(row, ["Tags Principaux"]) or "",
                "notes": pick_field(row, ["Notes"]) or "",
                "dossier_source": pick_field(row, ["Dossier Source"]) or "",
                "indiepattern_match": pick_field(row, ["✅ Match"]) or "",
                "indiepattern_titre": pick_field(row, ["IndiePattern Titre"]) or "",
                "indiepattern_url": pick_field(row, ["IndiePattern URL"]) or "",
                "indiepattern_description": pick_field(row, ["IndiePattern Description"]) or "",
                "indiepattern_keywords": pick_field(row, ["IndiePattern Keywords"]) or "",
            }
            
            document_id = f"listing_{product.number or index + 1}"
            
            try:
                r = requests.post(
                    f"{endpoint}/databases/{db_id}/collections/{collection_id}/documents",
                    headers=headers,
                    json={"documentId": document_id, "data": doc, "permissions": []},
                    timeout=30,
                )
                if r.status_code in (200, 201):
                    ok += 1
                else:
                    fail += 1
                    if fail <= 5:
                        errors.append(f"Row {index+1}: {r.json().get('message', r.text)[:100]}")
            except Exception as e:
                fail += 1
                if fail <= 5:
                    errors.append(f"Row {index+1}: {str(e)[:100]}")
            
            if (index + 1) % 10 == 0:
                push(job_id, "log", f"Synced {index+1}/{len(products)}")
        
        push(job_id, "done", {"ok": ok, "fail": fail, "total": len(products), "errors": errors[:5]})
    except Exception as exc:
        push(job_id, "error", str(exc))
    finally:
        jobs[job_id].put(None)


@woo_bp.post("/api/sync-sheet")
def api_sync_sheet() -> Response:
    config = load_config()
    try:
        rows = load_sheet(config.get("sheet_url") or DEFAULT_SHEET_URL)
        save_sheet_cache(rows)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
    # Build stats
    cats: dict[str, int] = {}
    prios: dict[str, int] = {}
    statuses: dict[str, int] = {}
    matched = 0
    for row in rows:
        d = row_to_dict(row)
        cats[d["categorie"]] = cats.get(d["categorie"], 0) + 1
        prios[d["priorite"]] = prios.get(d["priorite"], 0) + 1
        statuses[d["statut_etsy"]] = statuses.get(d["statut_etsy"], 0) + 1
        if d["indiepattern_match"]:
            matched += 1
    return jsonify({
        "ok": True,
        "count": len(rows),
        "matched": matched,
        "categories": cats,
        "priorities": prios,
        "statuses": statuses,
    })


@woo_bp.get("/api/sheet-stats")
def api_sheet_stats() -> Response:
    meta = sheet_cache_meta()
    if not meta["synced"]:
        return jsonify({"synced": False})
    rows = load_sheet_cached()
    cats: dict[str, int] = {}
    prios: dict[str, int] = {}
    statuses: dict[str, int] = {}
    matched = 0
    for row in rows:
        d = row_to_dict(row)
        cats[d["categorie"]] = cats.get(d["categorie"], 0) + 1
        prios[d["priorite"]] = prios.get(d["priorite"], 0) + 1
        statuses[d["statut_etsy"]] = statuses.get(d["statut_etsy"], 0) + 1
        if d["indiepattern_match"]:
            matched += 1
    return jsonify({**meta, "categories": cats, "priorities": prios, "statuses": statuses, "matched": matched})


@woo_bp.post("/api/sync-appwrite")
def api_sync_appwrite() -> Response:
    config = load_config()
    
    if not config.get("appwrite_endpoint") or not config.get("appwrite_project_id") or not config.get("appwrite_api_key"):
        return jsonify({"error": "Appwrite not configured. Add appwrite_endpoint, appwrite_project_id, appwrite_api_key to config.json"}), 400
    
    job_id = str(int(time.time() * 1000))
    jobs[job_id] = queue.Queue()
    thread = threading.Thread(target=run_appwrite_sync, args=(job_id, config), daemon=True)
    thread.start()
    
    return jsonify({"job_id": job_id})


@woo_bp.post("/api/preview")
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


@woo_bp.post("/api/start")
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


@woo_bp.post("/api/ai-generate")
def api_ai_generate() -> Response:
    data = request.get_json(force=True)
    config = load_config()
    field = data.get("field", "")
    product = data.get("product") or {}
    if field not in {"title", "description", "short_description", "tags"}:
        return jsonify({"error": "Invalid field."}), 400
    api_key = config.get("openrouter_api_key")
    if not api_key:
        return jsonify({"text": local_generate(field, product), "source": "local"})
    system_prompt = (
        "You are an expert copywriter specialising in digital sewing patterns sold on WooCommerce and Etsy. "
        "Your copy is warm, enthusiastic, and persuasive. You highlight the joy of creating handmade garments, "
        "the quality of the pattern, ease of use, and the value of an instant digital download. "
        "Never use generic filler. Make every sentence sell."
    )
    reference_description = str(product.get("indiepattern_description") or "").strip()
    reference_title = str(product.get("indiepattern_titre") or "").strip()
    style_hint = (
        "If a competitor reference is provided, mirror its energy, specificity, and structure, "
        "but never copy wording verbatim. Keep the result unique."
    )
    instructions = {
        "title": (
            "Write one SEO-optimised WooCommerce product title for this sewing pattern. "
            "Include the pattern name, key style words, and 'PDF Sewing Pattern | Instant Download'. "
            "Keep it under 120 characters. Return ONLY the title, no quotes. "
            f"{style_hint}"
        ),
        "description": (
            "Write a LONG, rich, persuasive WooCommerce product description for this sewing pattern. "
            "Structure it with these clearly separated sections (use HTML-friendly line breaks, not markdown):\n"
            "1. An exciting opening paragraph (3-4 sentences) that paints a picture of the finished garment and makes the buyer excited.\n"
            "2. A 'What You Will Make' section describing the style, fit, and design details in vivid detail (4-6 sentences).\n"
            "3. A 'Who Is This Pattern For?' section covering skill level, body types, occasions to wear it (3-4 sentences).\n"
            "4. A 'What's Included' bullet list: A0 copy-shop PDF, A4/US Letter home-print PDF, step-by-step sewing instructions with illustrations, size chart, fabric recommendations.\n"
            "5. A 'Why You Will Love It' bullet list: 5-6 strong selling points (instant download, print at home, professional results, beginner-friendly instructions, layered PDF, etc.).\n"
            "6. A 'Fabric Suggestions' section with 3-4 specific fabric types and why they work.\n"
            "7. A closing call-to-action paragraph (2-3 sentences) urging the buyer to add to cart now.\n"
            "Total length: at least 400 words. Return ONLY the description text, no markdown headers. "
            f"{style_hint}"
        ),
        "tags": (
            "Write exactly 12 short SEO tags for this sewing pattern. "
            "Return ONLY a comma-separated list, no numbering, no explanations."
        ),
        "short_description": (
            "Write a very persuasive WooCommerce short description (max 320 characters). "
            "Make it emotional, sales-driven, and exciting. Emphasize instant download, ease of sewing, and excellent value for money. "
            "If price is low, hint that it is a smart deal. Return ONLY the short description text. "
            f"{style_hint}"
        ),
    }
    prompt = (
        f"Pattern name / title: {product.get('title', '')}\n"
        f"Category: {product.get('category', '')}\n"
        f"Existing description (for context, you can improve it): {product.get('description', '')}\n"
        f"Price (USD): {product.get('price', '')}\n"
        f"Existing tags: {product.get('tags', '')}\n\n"
        f"Competitor title reference (optional): {reference_title}\n"
        f"Competitor description reference (optional): {reference_description}\n\n"
        f"Task: {instructions[field]}"
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
                "model": config.get("openrouter_model", "google/gemini-2.5-flash-preview"),
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.8,
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


@woo_bp.post("/api/extract-batch")
def api_extract_batch() -> Response:
    data = request.get_json(force=True)
    indexes = data.get("indexes", [])
    products = scan_folders()
    sheet_rows = load_sheet_cached()
    results = []
    for idx in indexes:
        if 0 <= idx < len(products):
            product = products[idx]
            choices = extract_candidate_images(Path(product.path))
            matched_row = match_sheet_row(product, sheet_rows, idx)
            sheet = row_to_dict(matched_row) if matched_row else {}
            results.append(
                {
                    "index": idx,
                    "folder": product.folder,
                    "clean_name": product.clean_name,
                    "number": product.number,
                    "pdfs": product.pdfs,
                    "warnings": product.warnings,
                    "images": choices,
                    "sheet": sheet,
                }
            )
    return jsonify(results)


def run_batch_upload(job_id: str, products_data: list[dict[str, Any]], all_products: list[ProductFolder], settings: dict[str, str]) -> None:
    try:
        sheet_rows: list[dict[str, str]] = []
        try:
            sheet_rows = load_sheet(settings.get("sheet_url") or DEFAULT_SHEET_URL)
        except Exception as exc:
            push(job_id, "log", f"Sheet update disabled: could not load sheet ({exc})")
        for item in products_data:
            idx = item.get("index")
            if idx is None or idx >= len(all_products):
                push(job_id, "log", f"Skipping invalid index {idx}")
                continue
            product = all_products[idx]
            push(job_id, "log", f"Uploading {product.folder}…")
            tags_raw = item.get("tags") or []
            if isinstance(tags_raw, str):
                tags_raw = [t.strip() for t in re.split(r"[,;|]", tags_raw) if t.strip()]
            preview = {
                "title": str(item.get("title") or product.clean_name),
                "description": str(item.get("description") or ""),
                "short_description": str(item.get("short_description") or ""),
                "price": str(item.get("price") or settings.get("price", "2.99")),
                "tags": tags_raw,
                "category": str(item.get("category") or settings.get("default_category", "")),
                "images": item.get("selected_images") or [],
                "pdfs": product.pdfs,
            }
            if not preview["images"]:
                push(job_id, "log", f"Skipping {product.folder} — no images selected.")
                continue
            created = create_wc_product(settings, preview, Path(product.path))
            try:
                row_idx = match_sheet_row_index(product, sheet_rows, idx)
                if row_idx is None:
                    push(job_id, "log", f"Sheet status skipped for {product.folder}: row not matched")
                else:
                    ok_sheet, msg = update_google_sheet_status(settings, product, row_idx, sheet_rows, status_value="Publié")
                    push(job_id, "log", msg if ok_sheet else f"Sheet status skipped for {product.folder}: {msg}")
            except Exception as exc:
                push(job_id, "log", f"Sheet status update failed for {product.folder}: {exc}")
            push(
                job_id,
                "product",
                {
                    "index": idx,
                    "title": preview["title"],
                    "woocommerce_id": created.get("id"),
                    "permalink": created.get("permalink"),
                    "folder": product.folder,
                    "wc_status": "Publié",
                },
            )
            push(job_id, "log", f"Created #{created.get('id')}: {preview['title']}")
        push(job_id, "done", "All products uploaded.")
    except Exception as exc:
        push(job_id, "error", str(exc))
    finally:
        jobs[job_id].put(None)


@woo_bp.post("/api/send-batch")
def api_send_batch() -> Response:
    data = request.get_json(force=True)
    products_data = data.get("products", [])
    if not products_data:
        return jsonify({"error": "No products provided."}), 400
    settings = load_config()
    all_products = scan_folders()
    job_id = str(int(time.time() * 1000))
    jobs[job_id] = queue.Queue()
    thread = threading.Thread(target=run_batch_upload, args=(job_id, products_data, all_products, settings), daemon=True)
    thread.start()
    return jsonify({"job_id": job_id})


@woo_bp.get("/api/events/<job_id>")
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
    _app = Flask(__name__)
    _app.register_blueprint(woo_bp)
    _app.run(host="127.0.0.1", port=5050, debug=True, threaded=True)
