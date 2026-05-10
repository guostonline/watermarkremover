"""
woo_upload.py — PatternsLabCo WooCommerce Product Creator
==========================================================
Usage:
    python woo_upload.py "Summer Dress"
    python woo_upload.py --all          (process all patterns)
    python woo_upload.py --list         (list available patterns)

Requirements:
    pip install requests pymupdf Pillow
"""

import sys, os, json, base64, re, argparse
import requests
from pathlib import Path
import fitz  # PyMuPDF

# ─── CONFIG ───────────────────────────────────────────────────────────────────
PATTERNS_DIR  = r"C:\Users\DELL\Documents\Etsy\500 باطرون 1"
WC_URL        = "https://patternslabco.com"
WC_KEY        = "ck_a0729810218b92ad1d876d824395225ffd076a4d"
WC_SECRET     = "cs_907df921d72fca8acf2fc9e89cb19a57c2222529"
WP_USERNAME   = "guostonline@gmail.com"
WP_APP_PASS   = "epOg NYnj XIBz Qzjt PcMy BLjs"   # spaces are fine

DEFAULT_PRICE       = "3.99"
DEFAULT_CATEGORY    = "Sewing Patterns"          # created if it doesn't exist
BONUS_TEXT          = "Easy Summer Dress Pattern" # shown in description bonus

# ─── HELPERS ──────────────────────────────────────────────────────────────────

def wc_auth():
    return (WC_KEY, WC_SECRET)

def wp_auth_header():
    token = base64.b64encode(f"{WP_USERNAME}:{WP_APP_PASS}".encode()).decode()
    return {"Authorization": f"Basic {token}"}

def log(msg, ok=True):
    icon = "✅" if ok else "❌"
    print(f"  {icon} {msg}")

# ─── FIND PATTERN FOLDER ──────────────────────────────────────────────────────

def find_pattern_folder(name: str) -> Path | None:
    name_lower = name.lower().replace("-", " ").replace("_", " ")
    base = Path(PATTERNS_DIR)
    for folder in base.iterdir():
        folder_clean = re.sub(r"^\d+[\s\-]+", "", folder.name).lower().strip()
        if name_lower in folder_clean or folder_clean in name_lower:
            return folder
    return None

def list_patterns():
    base = Path(PATTERNS_DIR)
    patterns = []
    for folder in sorted(base.iterdir()):
        if folder.is_dir():
            clean = re.sub(r"^\d+[\s\-]+", "", folder.name).strip()
            patterns.append(clean)
    return patterns

# ─── EXTRACT COVER IMAGE FROM PDF ─────────────────────────────────────────────

def extract_cover_image(folder: Path) -> bytes | None:
    """
    Look for the sewing guide / instructions PDF and extract the
    main product photo from page 1 (embedded JPEG).
    Fallback: render page 1 as high-res PNG.
    """
    # Priority: sewing guide > instructions > A4 pattern
    pdf_priority = ["guide", "instruction", "sewing", "a4", "letter"]
    pdfs = list(folder.glob("*.pdf"))

    def pdf_score(p):
        name = p.name.lower()
        for i, kw in enumerate(pdf_priority):
            if kw in name:
                return i
        return 99

    pdfs.sort(key=pdf_score)
    if not pdfs:
        return None

    for pdf_path in pdfs:
        doc = fitz.open(str(pdf_path))
        page = doc[0]

        # Try embedded image first (best quality)
        images = page.get_images(full=True)
        for img_info in images:
            xref = img_info[0]
            base_img = doc.extract_image(xref)
            w, h = base_img["width"], base_img["height"]
            # Only use reasonably large images (product photo, not icon)
            if w >= 400 and h >= 400:
                doc.close()
                img_bytes = base_img["image"]
                print(f"    📷 Cover from embedded image: {w}x{h} ({len(img_bytes)//1024}KB) — {pdf_path.name}")
                return img_bytes

        # Fallback: render full page at 2x
        mat = fitz.Matrix(2.0, 2.0)
        pix = page.get_pixmap(matrix=mat)
        doc.close()
        img_bytes = pix.tobytes("jpeg", jpg_quality=88)
        print(f"    📷 Cover from page render: {pix.width}x{pix.height} ({len(img_bytes)//1024}KB) — {pdf_path.name}")
        return img_bytes

    return None

# ─── UPLOAD IMAGE TO WORDPRESS MEDIA ──────────────────────────────────────────

def upload_image(img_bytes: bytes, filename: str) -> int | None:
    """Upload image bytes to WordPress media library. Returns media ID."""
    url = f"{WC_URL}/wp-json/wp/v2/media"
    headers = wp_auth_header()
    headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    headers["Content-Type"] = "image/jpeg"

    r = requests.post(url, headers=headers, data=img_bytes, timeout=60)
    if r.status_code in (200, 201):
        media_id = r.json()["id"]
        media_url = r.json().get("source_url", "")
        log(f"Image uploaded → ID {media_id}  {media_url}")
        return media_id
    else:
        log(f"Image upload failed: {r.status_code} — {r.text[:200]}", ok=False)
        return None

# ─── GET OR CREATE WOOCOMMERCE CATEGORY ───────────────────────────────────────

def get_or_create_category(name: str) -> int:
    """Return category ID, creating it if it doesn't exist."""
    r = requests.get(
        f"{WC_URL}/wp-json/wc/v3/products/categories",
        auth=wc_auth(),
        params={"search": name, "per_page": 10},
        timeout=15
    )
    if r.status_code == 200:
        for cat in r.json():
            if cat["name"].lower() == name.lower():
                log(f"Category found: '{name}' (ID {cat['id']})")
                return cat["id"]

    # Create it
    r2 = requests.post(
        f"{WC_URL}/wp-json/wc/v3/products/categories",
        auth=wc_auth(),
        json={"name": name},
        timeout=15
    )
    if r2.status_code in (200, 201):
        cat_id = r2.json()["id"]
        log(f"Category created: '{name}' (ID {cat_id})")
        return cat_id

    log(f"Category error: {r2.text[:100]}", ok=False)
    return 0

# ─── BUILD PRODUCT DESCRIPTION ────────────────────────────────────────────────

def build_description(pattern_name: str) -> str:
    return f"""<p><strong>{pattern_name} Sewing Pattern</strong>, perfect for Beginners 🪡</p>

<p>This pattern comes with an illustrated sewing guide with step by step instructions, making it super easy to make your own garment. If you're looking for a beginner friendly project that will take 2 hours to make then this is perfect for you!</p>

<p><strong>Pattern Includes:</strong><br>
✔️ Sizes: XS-XXXL<br>
✔️ Seam allowance included (1cm)<br>
✔️ A4/US Letter size (print at home) and A0 size (print at copy shop)<br>
✔️ Step-by-step instructions<br>
✔️ Layered Patterns: Print only your size and save ink!<br>
✔️ Instant Download! Receive the sewing patterns instantly after purchasing.</p>

<p>🎁 <strong>Bonus:</strong> {BONUS_TEXT}</p>

<p><em>If you are having any problems understanding/making the pattern don't hesitate to contact me! I am here to help. ♥ Happy Sewing ♥</em></p>"""

def build_short_description(pattern_name: str) -> str:
    return f"<p>Instant digital download PDF sewing pattern — {pattern_name}. Sizes XS-XXXL. A4/Letter/A0 formats included. Beginner-friendly with illustrated step-by-step guide.</p>"

# ─── CREATE WOOCOMMERCE PRODUCT ───────────────────────────────────────────────

def create_woo_product(pattern_name: str, folder: Path, image_id: int | None, category_id: int) -> dict | None:
    slug = re.sub(r"[^a-z0-9]+", "-", pattern_name.lower()).strip("-")

    product = {
        "name":              f"{pattern_name} Sewing Pattern – Beginner-Friendly PDF | Sizes XS-XXXL",
        "slug":              f"{slug}-sewing-pattern",
        "type":              "simple",
        "status":            "draft",           # draft first so you can verify!
        "featured":          False,
        "catalog_visibility":"visible",
        "description":       build_description(pattern_name),
        "short_description": build_short_description(pattern_name),
        "sku":               f"PLC-{slug[:30]}",
        "regular_price":     DEFAULT_PRICE,
        "downloadable":      True,
        "virtual":           True,
        "download_limit":    -1,
        "download_expiry":   -1,
        "downloads":         [],
        "categories":        [{"id": category_id}] if category_id else [],
        "tags": [
            {"name": "PDF Pattern"},
            {"name": "Sewing"},
            {"name": "Digital Download"},
            {"name": "PatternsLabCo"},
            {"name": "Beginner Friendly"},
        ],
        "images": [{"id": image_id}] if image_id else [],
        "meta_data": [
            {"key": "_source_folder", "value": folder.name},
        ],
    }

    r = requests.post(
        f"{WC_URL}/wp-json/wc/v3/products",
        auth=wc_auth(),
        json=product,
        timeout=30
    )

    if r.status_code in (200, 201):
        p = r.json()
        log(f"Product created (DRAFT) → ID {p['id']}")
        log(f"Edit URL: {WC_URL}/wp-admin/post.php?post={p['id']}&action=edit")
        log(f"Preview:  {p.get('permalink','')}")
        return p
    else:
        log(f"Product creation failed: {r.status_code}", ok=False)
        print(f"    {r.text[:400]}")
        return None

# ─── MAIN WORKFLOW ────────────────────────────────────────────────────────────

def process_pattern(name: str) -> bool:
    print(f"\n{'='*55}")
    print(f"  📂 Pattern: {name}")
    print(f"{'='*55}")

    # 1. Find folder
    folder = find_pattern_folder(name)
    if not folder:
        log(f"Folder not found for '{name}'", ok=False)
        return False
    log(f"Folder: {folder.name}")

    # 2. Extract cover image
    print("  Extracting cover image...")
    img_bytes = extract_cover_image(folder)
    media_id = None
    if img_bytes:
        filename = f"{re.sub(r'[^a-z0-9]+', '-', name.lower())}-pattern.jpg"
        media_id = upload_image(img_bytes, filename)
    else:
        log("No cover image found — product will have no image", ok=False)

    # 3. Get/create category
    cat_id = get_or_create_category(DEFAULT_CATEGORY)

    # 4. Create product
    product = create_woo_product(name, folder, media_id, cat_id)

    if product:
        # Save result to JSON for reference
        result_file = Path(r"C:\Users\DELL\Dev\watermarkremover\woo_upload_results.json")
        results = {}
        if result_file.exists():
            with open(result_file) as f:
                results = json.load(f)
        results[name] = {
            "product_id":   product["id"],
            "permalink":    product.get("permalink",""),
            "edit_url":     f"{WC_URL}/wp-admin/post.php?post={product['id']}&action=edit",
            "image_id":     media_id,
            "status":       "draft",
        }
        with open(result_file, "w") as f:
            json.dump(results, f, indent=2)
        print(f"\n  💾 Saved to woo_upload_results.json")
        return True

    return False

# ─── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Upload patterns to WooCommerce")
    parser.add_argument("pattern", nargs="?", help="Pattern name, e.g. 'Summer Dress'")
    parser.add_argument("--all",  action="store_true", help="Process all patterns")
    parser.add_argument("--list", action="store_true", help="List all available patterns")
    args = parser.parse_args()

    if args.list:
        patterns = list_patterns()
        print(f"\n{len(patterns)} patterns available:\n")
        for p in patterns:
            print(f"  • {p}")
        sys.exit(0)

    if args.all:
        patterns = list_patterns()
        print(f"\nProcessing all {len(patterns)} patterns...")
        ok = 0
        for p in patterns:
            if process_pattern(p):
                ok += 1
        print(f"\n✅ Done: {ok}/{len(patterns)} products created")
    elif args.pattern:
        process_pattern(args.pattern)
    else:
        parser.print_help()
        print("\nExample: python woo_upload.py \"Summer Dress\"")
