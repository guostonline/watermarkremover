import os
import uuid
import tempfile
import re
import traceback
import math
import logging
import zlib
import csv
import json
import hashlib
import base64
import hmac
import time
import secrets
from io import BytesIO
from datetime import datetime, timezone, timedelta
from flask import Flask, request, jsonify, send_file, render_template, Response, make_response, has_request_context
import pikepdf
from PIL import Image
from posthog import Posthog
from dotenv import load_dotenv
import requests
import cloudscraper
try:
    from curl_cffi import requests as cffi_requests
    _HAS_CURL_CFFI = True
except ImportError:
    _HAS_CURL_CFFI = False
from google.oauth2 import service_account
from googleapiclient.discovery import build
from bs4 import BeautifulSoup
from urllib.parse import quote

load_dotenv(override=True)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

app = Flask(__name__, template_folder="templates", static_folder="static")

from woocommerce_auto_save.app import woo_bp
app.register_blueprint(woo_bp, url_prefix="/woo")

import sys as _sys
_sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "article"))
from article.app import article_bp
app.register_blueprint(article_bp, url_prefix="/article")

UPLOAD_FOLDER = tempfile.mkdtemp()
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WAITLIST_CSV = os.path.join(BASE_DIR, "waitlist.csv")
STATS_FILE = os.path.join(BASE_DIR, "stats.json")
INVITES_FILE = os.path.join(BASE_DIR, "invites.json")
app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024

POSTHOG_KEY = os.environ.get("POSTHOG_API_KEY", "")
POSTHOG_HOST = os.environ.get("POSTHOG_HOST", "https://us.i.posthog.com")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "changeme123")
RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
APP_URL = os.environ.get("APP_URL", "http://localhost:5000")
PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY", "")

SETTINGS_FILE = os.path.join(BASE_DIR, "settings.json")

def load_settings():
    defaults = {"pexels_api_key": ""}
    try:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return defaults

def save_settings(settings):
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2)
    except Exception:
        pass

posthog = Posthog(project_api_key=POSTHOG_KEY, host=POSTHOG_HOST)


def generate_token():
    payload = f"{ADMIN_PASSWORD}:{int(time.time()) // 3600}"
    return hmac.new(payload.encode(), digestmod=hashlib.sha256).hexdigest()[:32]


ADMIN_TOKEN = generate_token()


def parse_form_float(name, default, min_value=None, max_value=None):
    raw = request.form.get(name, default)
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a number")
    if min_value is not None and value < min_value:
        raise ValueError(f"{name} must be at least {min_value}")
    if max_value is not None and value > max_value:
        raise ValueError(f"{name} must be at most {max_value}")
    return value


def load_stats():
    defaults = {"total_processes": 0, "success_processes": 0, "error_processes": 0,
                 "remove_processes": 0, "process_processes": 0, "stamp_processes": 0,
                 "logo_stamps": 0, "total_bytes_processed": 0,
                 "daily": {}, "unique_sessions": [], "recent_events": []}
    try:
        if os.path.exists(STATS_FILE):
            with open(STATS_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
            defaults.update(saved)
    except Exception:
        pass
    return defaults


def save_stats(stats):
    try:
        with open(STATS_FILE, "w", encoding="utf-8") as f:
            json.dump(stats, f)
    except Exception:
        pass


def record_event(event_type, session_id="", mode="", filename="", file_size=0,
                  success=True, error_reason="", has_logo=False, position=""):
    stats = load_stats()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if today not in stats.get("daily", {}):
        if not isinstance(stats.get("daily"), dict):
            stats["daily"] = {}
        stats["daily"][today] = {"success": 0, "error": 0, "bytes": 0, "sessions": []}
    day = stats["daily"][today]

    if success:
        stats["total_processes"] += 1
        stats["success_processes"] += 1
        day["success"] += 1
        if mode == "remove":
            stats["remove_processes"] += 1
        elif mode == "process":
            stats["process_processes"] += 1
            if has_logo:
                stats["logo_stamps"] += 1
        elif mode == "stamp":
            stats["stamp_processes"] += 1
    else:
        stats["total_processes"] += 1
        stats["error_processes"] += 1
        day["error"] += 1

    if file_size:
        stats["total_bytes_processed"] = stats.get("total_bytes_processed", 0) + file_size
        day["bytes"] += file_size

    if session_id:
        if session_id not in stats.get("unique_sessions", []):
            if not isinstance(stats.get("unique_sessions"), list):
                stats["unique_sessions"] = []
            stats["unique_sessions"].append(session_id)
            if len(stats["unique_sessions"]) > 10000:
                stats["unique_sessions"] = stats["unique_sessions"][-5000:]
        if session_id not in day.get("sessions", []):
            day["sessions"].append(session_id)

    event = {"type": event_type, "mode": mode, "success": success,
             "ts": datetime.now(timezone.utc).isoformat()}
    if filename:
        event["filename"] = filename
    if file_size:
        event["file_size"] = file_size
    if error_reason:
        event["error"] = error_reason
    if has_logo:
        event["has_logo"] = True
    if position:
        event["position"] = position

    if not isinstance(stats.get("recent_events"), list):
        stats["recent_events"] = []
    stats["recent_events"].insert(0, event)
    stats["recent_events"] = stats["recent_events"][:100]

    stats["daily"][today] = day
    save_stats(stats)

    if success and session_id:
        inv_token = request.cookies.get("invite_token", "") if has_request_context() else ""
        if inv_token:
            invites = load_invites()
            for inv in invites:
                if inv["token"] == inv_token and not inv.get("used_at"):
                    inv["used_at"] = datetime.now(timezone.utc).isoformat()
                    save_invites(invites)
                    break


def load_invites():
    try:
        if os.path.exists(INVITES_FILE):
            with open(INVITES_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return []


def save_invites(invites):
    try:
        with open(INVITES_FILE, "w", encoding="utf-8") as f:
            json.dump(invites, f, indent=2)
    except Exception:
        pass


def send_invite_email(email, token):
    import resend
    resend.api_key = RESEND_API_KEY
    invite_url = f"{APP_URL}/app?invite={token}"
    params = {
        "from": "PDF Clean <onboarding@resend.dev>",
        "to": [email],
        "subject": "You're in — try PDF Clean",
        "text": f"""Hey,

Thanks for signing up for PDF Clean!

I just opened up early access and wanted to give you a direct link to try it:

{invite_url}

It removes watermarks from PDFs instantly — just upload and download.
No signup needed for now.

I'd love to hear what you think. Reply to this email if you have
any questions or feedback.

— PDF Clean Team""",
    }
    try:
        r = resend.Emails.send(params)
        return {"ok": True, "id": r.get("id", "")}
    except Exception as e:
        log.error(f"Email send error: {e}")
        return {"ok": False, "error": str(e)}


def check_admin_auth(request):
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        token = auth[7:]
        return token in (ADMIN_TOKEN, os.environ.get("ADMIN_TOKEN", ""))
    return False


def get_session_id():
    sid = request.cookies.get("ph_sid")
    if not sid:
        sid = uuid.uuid4().hex
    return sid


@app.after_request
def set_session_cookie(response):
    sid = request.cookies.get("ph_sid")
    if not sid:
        sid = get_session_id()
        response.set_cookie("ph_sid", sid, max_age=365 * 24 * 60 * 60, httponly=True, samesite="Lax")
    return response


def remove_artifact_watermark(data):
    data = re.sub(
        rb"/Artifact\s*<<[^>]*Watermark[^>]*>>\s*BDC.*?EMC\s*\n?",
        b"",
        data,
        flags=re.DOTALL,
    )
    return data


def remove_oc_watermark_layer(data, oc_name_bytes):
    pattern = (
        rb"/OC\s+"
        + re.escape(oc_name_bytes)
        + rb"\s+BDC\s*?EMC\s*\n?"
    )
    data = re.sub(pattern, b"", data, flags=re.DOTALL)
    return data


def remove_indie_pattern_text(data):
    # Removes BT...ET blocks containing "Indie" or "Patter"
    def replacement(match):
        block = match.group(0)
        if b"Indie" in block or b"Patter" in block:
            return b""
        return block

    return re.sub(rb"BT.*?ET", replacement, data, flags=re.DOTALL)


def disable_watermark_ocg(pdf):
    ocprops = pdf.Root.get("/OCProperties")
    if ocprops is None:
        return 0

    ocgs = ocprops.get("/OCGs")
    if ocgs is None:
        return 0

    removed = 0
    watermark_ocgs = []
    for ocg in list(ocgs):
        if not isinstance(ocg, pikepdf.Dictionary):
            continue
        name = str(ocg.get("/Name", "")).lower()
        if "watermark" in name:
            watermark_ocgs.append(ocg)

    d = ocprops.get("/D")
    if d is not None:
        for key in ["/ON", "/OFF"]:
            arr = d.get(key)
            if isinstance(arr, pikepdf.Array):
                new_arr = pikepdf.Array(
                    [x for x in arr if x not in watermark_ocgs]
                )
                d[key] = new_arr

        order = d.get("/Order")
        if isinstance(order, pikepdf.Array):
            d["/Order"] = pikepdf.Array(
                [x for x in order if x not in watermark_ocgs]
            )

    return len(watermark_ocgs)


def find_watermark_gs_keys(page):
    wm_gs_keys = set()
    res = page.get("/Resources")
    if res is None or not isinstance(res, pikepdf.Dictionary):
        return wm_gs_keys
    gs_dict = res.get("/ExtGState")
    if gs_dict is None or not isinstance(gs_dict, pikepdf.Dictionary):
        return wm_gs_keys
    for gname in list(gs_dict.keys()):
        try:
            gobj = gs_dict[gname]
            if not isinstance(gobj, pikepdf.Dictionary):
                continue
            ca = gobj.get("/ca")
            CA = gobj.get("/CA")
            sa = gobj.get("/SA")
            is_semi_transparent = False
            if ca is not None:
                ca_val = float(ca)
                if 0.4 < ca_val < 0.6:
                    is_semi_transparent = True
            if CA is not None:
                ca_val = float(CA)
                if 0.4 < ca_val < 0.6:
                    is_semi_transparent = True
            smask = gobj.get("/SMask")
            if is_semi_transparent and smask != pikepdf.Name("/None"):
                continue
            if is_semi_transparent:
                wm_gs_keys.add(str(gname))
        except Exception:
            continue
    return wm_gs_keys


def replace_model_images(pdf, front_bytes=None, back_bytes=None):
    if not front_bytes and not back_bytes:
        return 0

    replaced_count = 0
    try:
        page = pdf.pages[0]
        
        def find_images(obj_dict, found_list, seen_objs):
            if not obj_dict:
                return
            for name, obj in obj_dict.items():
                obj_id = obj.objgen if hasattr(obj, "objgen") else id(obj)
                if obj_id in seen_objs:
                    continue
                seen_objs.add(obj_id)
                
                if obj.get("/Subtype") == "/Image":
                    w = int(obj.get("/Width", 0))
                    h = int(obj.get("/Height", 0))
                    if w > 50 and h > 50:  # Filter out small icons/dots
                        found_list.append({
                            "name": name,
                            "parent_dict": obj_dict,
                            "area": w * h,
                            "obj": obj,
                            "w": w,
                            "h": h
                        })
                elif obj.get("/Subtype") == "/Form":
                    res = obj.get("/Resources")
                    if res:
                        find_images(res.get("/XObject"), found_list, seen_objs)

        images_found = []
        resources = page.get("/Resources")
        if resources:
            find_images(resources.get("/XObject"), images_found, set())

        # Sort by area descending to find the main model images
        images_found.sort(key=lambda x: x["area"], reverse=True)

        replacement_images = []
        if front_bytes: replacement_images.append(front_bytes)
        if back_bytes: replacement_images.append(back_bytes)

        # Special case: If 2 images provided but only 1 found, merge them side-by-side
        if len(replacement_images) == 2 and len(images_found) == 1:
            target = images_found[0]
            img1 = Image.open(BytesIO(front_bytes))
            img2 = Image.open(BytesIO(back_bytes))
            
            # Create a side-by-side merge
            total_w = img1.width + img2.width
            max_h = max(img1.height, img2.height)
            merged = Image.new("RGB", (total_w, max_h), (255, 255, 255))
            merged.paste(img1, (0, 0))
            merged.paste(img2, (img1.width, 0))
            
            buf = BytesIO()
            merged.save(buf, format="JPEG", quality=85)
            compressed_data = buf.getvalue()
            
            new_image_stream = pikepdf.Stream(pdf, compressed_data)
            new_image_stream.Type = pikepdf.Name("/XObject")
            new_image_stream.Subtype = pikepdf.Name("/Image")
            new_image_stream.Width = merged.width
            new_image_stream.Height = merged.height
            new_image_stream.ColorSpace = pikepdf.Name("/DeviceRGB")
            new_image_stream.BitsPerComponent = 8
            new_image_stream.Filter = pikepdf.Name("/DCTDecode")
            
            target["parent_dict"][target["name"]] = new_image_stream
            replaced_count = 1
            log.info(f"Merged 2 images into 1 target {target['name']}")
        else:
            for i, img_data in enumerate(replacement_images):
                if i < len(images_found):
                    target = images_found[i]
                    
                    new_img = Image.open(BytesIO(img_data))
                    if new_img.mode != "RGB":
                        new_img = new_img.convert("RGB")
                    
                    buf = BytesIO()
                    new_img.save(buf, format="JPEG", quality=85)
                    compressed_data = buf.getvalue()

                    new_image_stream = pikepdf.Stream(pdf, compressed_data)
                    new_image_stream.Type = pikepdf.Name("/XObject")
                    new_image_stream.Subtype = pikepdf.Name("/Image")
                    new_image_stream.Width = new_img.width
                    new_image_stream.Height = new_img.height
                    new_image_stream.ColorSpace = pikepdf.Name("/DeviceRGB")
                    new_image_stream.BitsPerComponent = 8
                    new_image_stream.Filter = pikepdf.Name("/DCTDecode")

                    target["parent_dict"][target["name"]] = new_image_stream
                    replaced_count += 1
                    log.info(f"Replaced image {target['name']} (area: {target['area']}) in parent dictionary.")

    except Exception as e:
        log.error(f"Error replacing model images: {str(e)}")
        log.error(traceback.format_exc())

    return replaced_count


def remove_watermark(input_path, output_path, front_bytes=None, back_bytes=None):
    with pikepdf.open(input_path) as pdf:
        pages_processed = 0
        wm_oc_names = []

        # Replace model images on first page if provided
        if front_bytes or back_bytes:
            replaced = replace_model_images(pdf, front_bytes, back_bytes)
            log.info(f"Replaced {replaced} model images on first page")

        ocprops = pdf.Root.get("/OCProperties")
        if ocprops is not None:
            ocgs = ocprops.get("/OCGs")
            if ocgs is not None:
                for ocg in ocgs:
                    if not isinstance(ocg, pikepdf.Dictionary):
                        continue
                    name = str(ocg.get("/Name", "")).lower()
                    if "watermark" in name:
                        name_str = str(ocg.get("/Name", ""))
                        wm_oc_names.append(name_str.lstrip("/").encode())
                        log.info(f"Found Watermark OCG: {ocg.get('/Name')}")

        oc_disabled = disable_watermark_ocg(pdf)
        log.info(f"Disabled {oc_disabled} watermark OCGs from viewing defaults")

        for page_num, page in enumerate(pdf.pages):
            try:
                contents = page.get("/Contents")
                if not contents:
                    continue

                if isinstance(contents, pikepdf.Array):
                    streams_list = list(contents)
                else:
                    streams_list = [contents]

                page_modified = False

                wm_gs_keys = find_watermark_gs_keys(page)

                for stream_obj in streams_list:
                    try:
                        if not hasattr(stream_obj, "read_bytes"):
                            continue
                        data = stream_obj.read_bytes()
                        original = data

                        data = remove_artifact_watermark(data)
                        data = remove_indie_pattern_text(data)

                        for wm_name in wm_oc_names:
                            data = remove_oc_watermark_layer(data, wm_name)

                        for gs_key in wm_gs_keys:
                            gs_bytes = gs_key.lstrip("/").encode()
                            pattern = (
                                rb"q\s+(?:[^\n]*\n){0,8}"
                                + rb"/" + re.escape(gs_bytes) + rb"\s+gs"
                                + rb"(?:[^\n]*\n){0,10}"
                                + rb"/\w+\s+Do"
                                + rb"(?:[^\n]*\n){0,2}"
                                + rb"Q\n?"
                            )
                            data = re.sub(pattern, b"", data)

                        pattern_gs2_simple = (
                            rb"q\s*/GS2\s+gs\s+[^\n]*cm\s*/\w+\s+Do\s*Q\n?"
                        )
                        data = re.sub(pattern_gs2_simple, b"", data)

                        pattern_gs3_simple = (
                            rb"q\s*/GS3\s+gs\s+[^\n]*cm\s*/\w+\s+Do\s*Q\n?"
                        )
                        data = re.sub(pattern_gs3_simple, b"", data)

                        # Generic fallback: remove q.../GS2 gs...Q blocks with Do calls
                        for gs_key in [b"GS2", b"GS3"]:
                            gs_pattern = (
                                rb"q\s+(?:[^\n]*\n){0,6}/"
                                + re.escape(gs_key)
                                + rb"\s+gs(?:[^\n]*\n){0,10}"
                                + rb"(?:/\w+\s+Do[^\n]*\n?){1,3}"
                                + rb"Q\n?"
                            )
                            data = re.sub(gs_pattern, b"", data)

                        data = re.sub(
                            rb"q\s+0\.9985809[^\n]*\n[^\n]*\n[^\n]*\n[^\n]*\n(?:[^\n]*\n){0,3}%\s*watermark\s+removed[^\n]*\nQ\n?",
                            b"",
                            data,
                        )
                        data = re.sub(
                            rb"q\s+0\.9985809[^\n]*\n[^\n]*\n[^\n]*\n(?:[^\n]*\n){0,5}%\s*watermark\s+removed[^\n]*\n?Q\n?",
                            b"",
                            data,
                        )

                        # Original patterns for specific watermark PDFs
                        for name_bytes_pat in [b"1348", b"2000"]:
                            pass  # handled below in xobject detection

                        # Remove XObject references inside watermark Form XObjects
                        res = page.get("/Resources")
                        if res is not None and isinstance(res, pikepdf.Dictionary):
                            xobjs = res.get("/XObject")
                            if xobjs is not None and isinstance(xobjs, pikepdf.Dictionary):
                                for xname in list(xobjs.keys()):
                                    try:
                                        xobj = xobjs[xname]
                                        if not isinstance(xobj, pikepdf.Dictionary):
                                            continue
                                        subtype = xobj.get("/Subtype")
                                        if subtype != pikepdf.Name("/Form"):
                                            continue
                                        inner_res = xobj.get("/Resources")
                                        if not isinstance(inner_res, pikepdf.Dictionary):
                                            continue
                                        inner_xobjs = inner_res.get("/XObject")
                                        if not isinstance(inner_xobjs, pikepdf.Dictionary):
                                            continue
                                        for iname in list(inner_xobjs.keys()):
                                            try:
                                                ixobj = inner_xobjs[iname]
                                                if not isinstance(ixobj, pikepdf.Dictionary):
                                                    continue
                                                ist = ixobj.get("/Subtype")
                                                if ist == pikepdf.Name("/Image"):
                                                    w = int(ixobj.get("/Width", 0))
                                                    h = int(ixobj.get("/Height", 0))
                                                    if (w == 1348 and h == 2000) or \
                                                       (w == 1848 and h == 2000):
                                                        wm_ref = str(xname).lstrip("/").encode()
                                                        pattern = (
                                                            rb"q\s+(?:[^\n]*\n){0,5}/"
                                                            + re.escape(wm_ref)
                                                            + rb"\s+Do\s+Q\n?"
                                                        )
                                                        data = re.sub(pattern, b"", data)
                                            except Exception:
                                                continue
                                    except Exception:
                                        continue

                        # Detect and remove watermark Form XObjects
                        wm_xobj_names = set()
                        if res is not None and isinstance(res, pikepdf.Dictionary):
                            xobjs = res.get("/XObject")
                            if xobjs is not None and isinstance(xobjs, pikepdf.Dictionary):
                                for name in list(xobjs.keys()):
                                    try:
                                        xobj = xobjs[name]
                                        if not isinstance(xobj, pikepdf.Dictionary):
                                            continue
                                        if xobj.get("/Subtype") != pikepdf.Name("/Form"):
                                            continue
                                        stream = xobj.read_bytes()
                                        
                                        # Also remove indie pattern text from within Form XObjects
                                        clean_stream = remove_indie_pattern_text(stream)
                                        if clean_stream != stream:
                                            xobj.write(clean_stream)
                                            page_modified = True
                                            stream = clean_stream

                                        is_watermark = False
                                        if b"/GS2 gs" in stream or b"/GS3 gs" in stream:
                                            if b"0.9985809" in stream:
                                                is_watermark = True
                                        if b"0.898 0.898 0.898 rg" in stream:
                                            is_watermark = True
                                        inner_res = xobj.get("/Resources")
                                        if isinstance(inner_res, pikepdf.Dictionary):
                                            inner_xobjs = inner_res.get("/XObject")
                                            if isinstance(inner_xobjs, pikepdf.Dictionary):
                                                for iname in list(inner_xobjs.keys()):
                                                    ixobj = inner_xobjs[iname]
                                                    if isinstance(ixobj, pikepdf.Dictionary):
                                                        ist = ixobj.get("/Subtype")
                                                        if ist == pikepdf.Name("/Image"):
                                                            w = int(ixobj.get("/Width", 0))
                                                            h = int(ixobj.get("/Height", 0))
                                                            if (w == 1348 and h == 2000) or \
                                                               (w == 1848 and h == 2000):
                                                                is_watermark = True
                                        if is_watermark:
                                            wm_xobj_names.add(str(name))
                                    except Exception:
                                        continue

                        for wm_name in wm_xobj_names:
                            name_bytes = wm_name.lstrip("/").encode()
                            pattern = (
                                rb"q\s+(?:[^\n]*\n){0,6}/"
                                + re.escape(name_bytes)
                                + rb"\s+Do\s+Q\n?"
                            )
                            data = re.sub(pattern, b"", data)
                            pattern2 = (
                                rb"/" + re.escape(name_bytes) + rb"\s+Do\n?"
                            )
                            data = re.sub(pattern2, b"", data)

                        if data != original:
                            try:
                                stream_obj.write(data)
                            except Exception:
                                pass
                            page_modified = True

                    except Exception:
                        continue

                # Delete watermark XObjects from resources
                res = page.get("/Resources")
                if res is not None and isinstance(res, pikepdf.Dictionary):
                    xobjs = res.get("/XObject")
                    if xobjs is not None and isinstance(xobjs, pikepdf.Dictionary):
                        for name in list(xobjs.keys()):
                            try:
                                xobj = xobjs[name]
                                if not isinstance(xobj, pikepdf.Dictionary):
                                    continue
                                if xobj.get("/Subtype") != pikepdf.Name("/Form"):
                                    continue
                                stream = xobj.read_bytes()
                                is_watermark = False
                                if b"/GS2 gs" in stream or b"/GS3 gs" in stream:
                                    if b"0.9985809" in stream:
                                        is_watermark = True
                                if b"0.898 0.898 0.898 rg" in stream:
                                    is_watermark = True
                                inner_res = xobj.get("/Resources")
                                if isinstance(inner_res, pikepdf.Dictionary):
                                    inner_xobjs = inner_res.get("/XObject")
                                    if isinstance(inner_xobjs, pikepdf.Dictionary):
                                        for iname in list(inner_xobjs.keys()):
                                            ixobj = inner_xobjs[iname]
                                            if isinstance(ixobj, pikepdf.Dictionary):
                                                ist = ixobj.get("/Subtype")
                                                if ist == pikepdf.Name("/Image"):
                                                    w = int(ixobj.get("/Width", 0))
                                                    h = int(ixobj.get("/Height", 0))
                                                    if (w == 1348 and h == 2000) or \
                                                       (w == 1848 and h == 2000):
                                                        is_watermark = True
                                if is_watermark:
                                    key = pikepdf.Name(name) if not str(name).startswith("/") else pikepdf.Name(str(name))
                                    try:
                                        del xobjs[name]
                                    except Exception:
                                        pass
                            except Exception:
                                continue

                if page_modified:
                    pages_processed += 1

            except Exception:
                log.warning(f"Skipping page {page_num + 1}: {traceback.format_exc()}")
                continue

        pdf.save(output_path)
        log.info(f"Done: processed {pages_processed} pages, disabled {oc_disabled} OCG layers")


@app.route("/")
def landing():
    return render_template("landing.html", posthog_key=POSTHOG_KEY, posthog_host=POSTHOG_HOST)


@app.route("/remove")
def remove_page():
    invite_token = request.args.get("invite", "")
    if invite_token:
        invites = load_invites()
        for inv in invites:
            if inv["token"] == invite_token:
                if not inv.get("clicked_at"):
                    inv["clicked_at"] = datetime.now(timezone.utc).isoformat()
                    save_invites(invites)
                break
        posthog.capture("invite_click", distinct_id=get_session_id(), properties={"invite_token": invite_token})
    embed = request.args.get("embed", "")
    resp = make_response(render_template("index.html", posthog_key=POSTHOG_KEY, posthog_host=POSTHOG_HOST, embed=bool(embed)))
    if invite_token:
        resp.set_cookie("invite_token", invite_token, max_age=30 * 24 * 60 * 60, httponly=True, samesite="Lax")
    return resp


@app.route("/app")
def tools_page():
    return render_template("tools.html")


@app.route("/app/listings/<int:index>")
def listing_details_page(index):
    return render_template("listing_details.html", index=index)


@app.route("/favicon.ico")
def favicon():
    return send_file(os.path.join(BASE_DIR, "static", "favicon.svg"), mimetype="image/svg+xml")


@app.route("/favicon.svg")
def favicon_svg():
    return send_file(os.path.join(BASE_DIR, "static", "favicon.svg"), mimetype="image/svg+xml")


@app.route("/site.webmanifest")
def webmanifest():
    return jsonify({
        "name": "PDF Clean",
        "short_name": "PDF Clean",
        "icons": [
            {"src": "/static/android-chrome-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "/static/android-chrome-512.png", "sizes": "512x512", "type": "image/png"},
            {"src": "/static/favicon.svg", "sizes": "any", "type": "image/svg+xml"}
        ],
        "theme_color": "#09090b",
        "background_color": "#09090b",
        "display": "standalone"
    })


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@app.route("/api/waitlist", methods=["POST"])
def waitlist():
    try:
        data = request.get_json(silent=True) or {}
    except Exception:
        data = {}
    email = (data.get("email") or "").strip().lower()
    if not email or not EMAIL_RE.match(email):
        return jsonify({"error": "Please enter a valid email address."}), 400
    existing = set()
    if os.path.exists(WAITLIST_CSV):
        with open(WAITLIST_CSV, "r", newline="", encoding="utf-8") as f:
            for row in csv.reader(f):
                if row:
                    existing.add(row[0].strip().lower())
    if email in existing:
        return jsonify({"ok": True, "message": "You're already on the list! We'll be in touch soon."})
    with open(WAITLIST_CSV, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([email, datetime.now(timezone.utc).isoformat()])
    log.info(f"Waitlist signup: {email}")
    sid = get_session_id()
    posthog.capture("waitlist_signup", distinct_id=sid, properties={"email": email})
    return jsonify({"ok": True, "message": "You're on the list! We'll notify you when we launch."})


@app.route("/api/settings")
def get_settings():
    settings = load_settings()
    return jsonify({
        "pexels_api_key": settings.get("pexels_api_key", "")
    })


@app.route("/api/settings", methods=["POST"])
def update_settings():
    data = request.get_json(silent=True) or {}
    settings = load_settings()
    if "pexels_api_key" in data:
        settings["pexels_api_key"] = data["pexels_api_key"].strip()
    save_settings(settings)
    return jsonify({"ok": True})


@app.route("/api/pexels/search")
def pexels_search():
    settings = load_settings()
    pexels_key = settings.get("pexels_api_key") or PEXELS_API_KEY
    if not pexels_key:
        return jsonify({"error": "Pexels API key not configured. Add it in Settings."}), 500
    query = request.args.get("query", "")
    page = request.args.get("page", 1)
    per_page = min(int(request.args.get("per_page", 15)), 80)
    if not query:
        return jsonify({"error": "Query parameter required"}), 400
    import urllib.request
    import urllib.parse
    params = urllib.parse.urlencode({"query": query, "page": page, "per_page": per_page})
    url = f"https://api.pexels.com/v1/search?{params}"
    req = urllib.request.Request(url, headers={"Authorization": pexels_key})
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode())
    except Exception as e:
        return jsonify({"error": f"Failed to fetch from Pexels: {str(e)}"}), 500
    photos = []
    for p in data.get("photos", []):
        photos.append({
            "id": p.get("id"),
            "url": p.get("url"),
            "photographer": p.get("photographer"),
            "photographer_url": p.get("photographer_url"),
            "src": p.get("src", {}),
            "alt": p.get("alt", "")
        })
    return jsonify({
        "photos": photos,
        "total_results": data.get("total_results", 0),
        "page": data.get("page", 1),
        "per_page": data.get("per_page", per_page)
    })


@app.route("/admin")
def admin_dashboard():
    return render_template("admin.html")


@app.route("/api/admin/login", methods=["POST"])
def admin_login():
    data = request.get_json(silent=True) or {}
    password = data.get("password", "")
    if password != ADMIN_PASSWORD:
        return jsonify({"error": "Invalid password"}), 401
    return jsonify({"token": ADMIN_TOKEN})


@app.route("/api/admin/invite", methods=["POST"])
def admin_invite():
    if not check_admin_auth(request):
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json(silent=True) or {}
    emails = data.get("emails", [])
    if not emails or not isinstance(emails, list):
        return jsonify({"error": "emails list required"}), 400
    emails = [e.strip().lower() for e in emails if e and isinstance(e, str)]
    if len(emails) > 100:
        return jsonify({"error": "Max 100 emails per batch"}), 400

    invites = load_invites()
    existing = {inv["email"]: inv for inv in invites}
    results = []

    for email in emails:
        if not EMAIL_RE.match(email):
            results.append({"email": email, "status": "invalid", "error": "bad email"})
            continue
        if email in existing:
            inv = existing[email]
            results.append({"email": email, "status": "already_sent", "token": inv["token"]})
            continue

        token = secrets.token_urlsafe(8)
        invite = {
            "email": email,
            "token": token,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "email_sent_at": None,
            "clicked_at": None,
            "used_at": None,
        }

        if RESEND_API_KEY:
            result = send_invite_email(email, token)
            if result.get("ok"):
                invite["email_sent_at"] = datetime.now(timezone.utc).isoformat()
                results.append({"email": email, "status": "sent", "token": token})
            else:
                results.append({"email": email, "status": "email_failed", "error": result.get("error", "")})
        else:
            invite["email_sent_at"] = datetime.now(timezone.utc).isoformat()
            results.append({"email": email, "status": "sent_no_email", "token": token})

        invites.append(invite)

    save_invites(invites)
    return jsonify({"results": results})


@app.route("/api/admin/invites")
def admin_invites():
    if not check_admin_auth(request):
        return jsonify({"error": "Unauthorized"}), 401
    invites = load_invites()
    sent = sum(1 for i in invites if i.get("email_sent_at"))
    clicked = sum(1 for i in invites if i.get("clicked_at"))
    used = sum(1 for i in invites if i.get("used_at"))
    return jsonify({
        "invites": invites,
        "summary": {"total": len(invites), "sent": sent, "clicked": clicked, "used": used},
    })


@app.route("/api/admin/invites/revoke", methods=["POST"])
def admin_invites_revoke():
    if not check_admin_auth(request):
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json(silent=True) or {}
    token = data.get("token", "")
    invites = load_invites()
    invites = [i for i in invites if i["token"] != token]
    save_invites(invites)
    return jsonify({"ok": True})


@app.route("/api/admin/stats")
def admin_stats():
    if not check_admin_auth(request):
        return jsonify({"error": "Unauthorized"}), 401

    waitlist = []
    if os.path.exists(WAITLIST_CSV):
        try:
            with open(WAITLIST_CSV, "r", newline="", encoding="utf-8") as f:
                for row in csv.reader(f):
                    if row and len(row) >= 2:
                        waitlist.append({"email": row[0].strip(), "created_at": row[1].strip()})
        except Exception:
            pass

    stats = load_stats()

    daily = stats.get("daily", {})
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    yesterday_dt = datetime.now(timezone.utc) - __import__("datetime").timedelta(days=1)
    yesterday = yesterday_dt.strftime("%Y-%m-%d")

    processes_today = daily.get(today, {}).get("success", 0) + daily.get(today, {}).get("error", 0)
    success_today = daily.get(today, {}).get("success", 0)
    error_today = daily.get(today, {}).get("error", 0)
    processes_yesterday = daily.get(yesterday, {}).get("success", 0) + daily.get(yesterday, {}).get("error", 0)
    sessions_today = len(daily.get(today, {}).get("sessions", []))
    sessions_yesterday = len(daily.get(yesterday, {}).get("sessions", []))
    bytes_today = daily.get(today, {}).get("bytes", 0)
    bytes_yesterday = daily.get(yesterday, {}).get("bytes", 0)

    recent_events = stats.get("recent_events", [])[:50]
    unique_sessions = len(stats.get("unique_sessions", []))

    success_rate = round((stats["success_processes"] / stats["total_processes"] * 100), 1) if stats["total_processes"] > 0 else 0

    error_breakdown = {}
    for ev in stats.get("recent_events", []):
        if not ev.get("success") and ev.get("error"):
            reason = ev["error"]
            short = reason if len(reason) < 60 else reason[:57] + "..."
            error_breakdown[short] = error_breakdown.get(short, 0) + 1

    top_errors = sorted(error_breakdown.items(), key=lambda x: x[1], reverse=True)[:5]

    daily_chart = []
    sorted_days = sorted(daily.keys(), reverse=True)[:14]
    for d in sorted_days:
        day_data = daily[d]
        daily_chart.append({"date": d, "success": day_data.get("success", 0),
                            "error": day_data.get("error", 0),
                            "bytes": day_data.get("bytes", 0),
                            "sessions": len(day_data.get("sessions", []))})

    logo_adoption = round((stats.get("logo_stamps", 0) / max(stats.get("success_processes", 1), 1)) * 100, 1)

    total_bytes = stats.get("total_bytes_processed", 0)
    def fmt_bytes(b):
        if b < 1024: return f"{b} B"
        if b < 1048576: return f"{b/1024:.1f} KB"
        if b < 1073741824: return f"{b/1048576:.1f} MB"
        return f"{b/1073741824:.1f} GB"

    result = {
        "stats": {
            "total_waitlist": len(waitlist),
            "total_processes": stats["total_processes"],
            "success_processes": stats["success_processes"],
            "error_processes": stats["error_processes"],
            "remove_processes": stats["remove_processes"],
            "process_processes": stats["process_processes"],
            "stamp_processes": stats["stamp_processes"],
            "logo_stamps": stats.get("logo_stamps", 0),
            "total_bytes_processed": total_bytes,
            "total_bytes_formatted": fmt_bytes(total_bytes),
            "success_rate": success_rate,
            "logo_adoption_rate": logo_adoption,
            "unique_sessions": unique_sessions,
            "processes_today": processes_today,
            "success_today": success_today,
            "error_today": error_today,
            "processes_yesterday": processes_yesterday,
            "sessions_today": sessions_today,
            "sessions_yesterday": sessions_yesterday,
            "bytes_today": bytes_today,
            "bytes_today_formatted": fmt_bytes(bytes_today),
            "bytes_yesterday": bytes_yesterday,
            "bytes_yesterday_formatted": fmt_bytes(bytes_yesterday),
            "top_errors": top_errors,
            "logo_adoption": logo_adoption,
        },
        "daily_chart": daily_chart,
        "recent_events": recent_events,
        "waitlist": waitlist,
        "invite_summary": {
            "total": len(load_invites()),
            "sent": sum(1 for i in load_invites() if i.get("email_sent_at")),
            "clicked": sum(1 for i in load_invites() if i.get("clicked_at")),
            "used": sum(1 for i in load_invites() if i.get("used_at")),
        },
    }

    return jsonify(result)


@app.route("/api/remove", methods=["POST"])
def handle_remove():
    if "file" not in request.files:
        return jsonify({"error": "No PDF uploaded"}), 400

    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "No file selected"}), 400

    if not f.filename.lower().endswith(".pdf"):
        return jsonify({"error": "Only PDF files are supported"}), 400

    uid = uuid.uuid4().hex[:12]
    input_path = os.path.join(UPLOAD_FOLDER, f"input_{uid}.pdf")
    output_path = os.path.join(UPLOAD_FOLDER, f"output_{uid}.pdf")
    sid = get_session_id()
    file_size = 0
    try:
        file_size = os.path.getsize(input_path)
    except Exception:
        pass

    try:
        f.save(input_path)
        file_size = os.path.getsize(input_path)
        
        front_file = request.files.get("front_model")
        back_file = request.files.get("back_model")
        
        front_bytes = front_file.read() if front_file else None
        back_bytes = back_file.read() if back_file else None

        remove_watermark(input_path, output_path, front_bytes, back_bytes)

        if not os.path.exists(output_path):
            return jsonify({"error": "Processing failed: no output generated"}), 500

        posthog.capture("pdf_process_success", distinct_id=sid, properties={"mode": "remove", "filename": f.filename})
        record_event("process", session_id=sid, mode="remove", filename=f.filename, file_size=file_size, success=True)
        return send_file(
            output_path,
            as_attachment=True,
            download_name=f"no_watermark_{f.filename}",
            mimetype="application/pdf",
        )
    except pikepdf._core.PasswordError:
        posthog.capture("pdf_process_error", distinct_id=sid, properties={"mode": "remove", "reason": "password_protected"})
        record_event("process", session_id=sid, mode="remove", filename=f.filename, file_size=file_size, success=False, error_reason="password_protected")
        return jsonify({"error": "This PDF is password-protected and cannot be processed"}), 400
    except pikepdf._core.HierarchyError as e:
        posthog.capture("pdf_process_error", distinct_id=sid, properties={"mode": "remove", "reason": "hierarchy_error"})
        record_event("process", session_id=sid, mode="remove", filename=f.filename, file_size=file_size, success=False, error_reason="hierarchy_error")
        return jsonify({"error": f"PDF structure error: {str(e)}"}), 400
    except Exception as e:
        log.error(f"Processing error: {traceback.format_exc()}")
        posthog.capture("pdf_process_error", distinct_id=sid, properties={"mode": "remove", "reason": str(e)})
        record_event("process", session_id=sid, mode="remove", filename=f.filename, file_size=file_size, success=False, error_reason=str(e))
        return jsonify({"error": f"Error processing PDF: {str(e)}"}), 500
    finally:
        for p in (input_path, output_path):
            try:
                if os.path.exists(p):
                    os.remove(p)
            except Exception:
                pass


@app.route("/api/extract-images", methods=["POST"])
def handle_extract_images():
    if "file" not in request.files:
        return jsonify({"error": "No PDF uploaded"}), 400

    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "No file selected"}), 400

    if not f.filename.lower().endswith(".pdf"):
        return jsonify({"error": "Only PDF files are supported"}), 400

    uid = uuid.uuid4().hex[:12]
    input_path = os.path.join(UPLOAD_FOLDER, f"input_{uid}.pdf")
    sid = get_session_id()
    file_size = 0

    try:
        f.save(input_path)
        file_size = os.path.getsize(input_path)

        images = []
        with pikepdf.open(input_path) as pdf:
            for page_idx, page in enumerate(pdf.pages):
                try:
                    resources = page.get("/Resources")
                    if not resources:
                        continue
                    xobjects = resources.get("/XObject")
                    if not xobjects:
                        continue

                    def extract_from_xobjects(xobj_dict, page_num):
                        if not xobj_dict:
                            return
                        for name in xobj_dict.keys():
                            obj = xobj_dict[name]
                            try:
                                obj = obj.get_object() if hasattr(obj, 'get_object') else obj
                            except Exception:
                                pass

                            if hasattr(obj, 'get') and obj.get("/Subtype") == "/Form":
                                form_resources = obj.get("/Resources")
                                if form_resources:
                                    form_xobjects = form_resources.get("/XObject")
                                    if form_xobjects:
                                        extract_from_xobjects(form_xobjects, page_num)
                                continue

                            if not hasattr(obj, 'get'):
                                continue
                            if obj.get("/Subtype") != "/Image":
                                continue

                            w = int(obj.get("/Width", 0))
                            h = int(obj.get("/Height", 0))
                            if w < 10 or h < 10:
                                continue

                            filters = obj.get("/Filter")
                            if isinstance(filters, pikepdf.Array):
                                filter_list = [str(f) for f in filters]
                            elif filters:
                                filter_list = [str(filters)]
                            else:
                                filter_list = []

                            color_space = obj.get("/ColorSpace")
                            num_components = 3
                            if color_space is not None:
                                cs_str = str(color_space)
                                if "/DeviceGray" in cs_str:
                                    num_components = 1
                                elif "/DeviceCMYK" in cs_str:
                                    num_components = 4

                            try:
                                raw_data = obj.read_raw_bytes()
                            except Exception:
                                try:
                                    raw_data = bytes(obj)
                                except Exception:
                                    continue

                            img = None

                            try:
                                if "/DCTDecode" in filter_list:
                                    img = Image.open(BytesIO(raw_data))
                                elif "/JPXDecode" in filter_list:
                                    img = Image.open(BytesIO(raw_data))
                                elif "/FlateDecode" in filter_list or not filter_list:
                                    try:
                                        decompressed = zlib.decompress(raw_data) if filter_list else raw_data
                                        mode = {1: "L", 3: "RGB", 4: "CMYK"}.get(num_components, "RGB")
                                        if num_components == 4:
                                            img = Image.frombytes("CMYK", (w, h), decompressed)
                                            img = img.convert("RGB")
                                        else:
                                            img = Image.frombytes(mode, (w, h), decompressed)
                                    except Exception:
                                        try:
                                            img = Image.open(BytesIO(raw_data))
                                        except Exception:
                                            continue
                                else:
                                    try:
                                        img = Image.open(BytesIO(raw_data))
                                    except Exception:
                                        continue
                            except Exception:
                                continue

                            if img is None:
                                continue

                            if img.mode == "CMYK":
                                img = img.convert("RGB")
                            elif img.mode not in ("RGB", "L", "RGBA", "P"):
                                img = img.convert("RGB")

                            if img.mode == "P":
                                img = img.convert("RGBA")

                            check = img.convert("RGB").resize((64, 64))
                            pixels = list(check.getdata())
                            mean = tuple(sum(c[i] for c in pixels) / len(pixels) for i in range(3))
                            variance = sum(sum((c[i] - mean[i]) ** 2 for i in range(3)) for c in pixels) / len(pixels)
                            if math.sqrt(variance) < 15:
                                continue

                            buf = BytesIO()
                            fmt = "PNG" if img.mode == "RGBA" else "JPEG"
                            img.save(buf, format=fmt, quality=90)
                            data_url = "data:image/" + ("png" if fmt == "PNG" else "jpeg") + ";base64," + base64.b64encode(buf.getvalue()).decode("utf-8")

                            clean_name = name.decode() if isinstance(name, bytes) else str(name)
                            clean_name = clean_name.lstrip("/").replace("/", "_")
                            filename = f"page{page_num + 1}_{clean_name}.{'png' if fmt == 'PNG' else 'jpg'}"

                            if len(images) < 200:
                                images.append({
                                    "filename": filename,
                                    "page": page_num + 1,
                                    "width": img.width,
                                    "height": img.height,
                                    "dataUrl": data_url,
                                })
                    extract_from_xobjects(xobjects, page_idx)
                except Exception:
                    continue

        posthog.capture("pdf_process_success", distinct_id=sid, properties={"mode": "extract_images", "filename": f.filename, "image_count": len(images)})
        record_event("process", session_id=sid, mode="extract_images", filename=f.filename, file_size=file_size, success=True)
        return jsonify({"images": images})

    except pikepdf._core.PasswordError:
        return jsonify({"error": "This PDF is password-protected and cannot be processed"}), 400
    except Exception as e:
        log.error(f"Extract images error: {traceback.format_exc()}")
        return jsonify({"error": f"Error extracting images: {str(e)}"}), 500
    finally:
        try:
            if os.path.exists(input_path):
                os.remove(input_path)
        except Exception:
            pass


@app.route("/api/process", methods=["POST"])
def handle_process():
    pdf_file = request.files.get("file")
    if not pdf_file:
        return jsonify({"error": "No PDF uploaded"}), 400
    if not pdf_file.filename or not pdf_file.filename.lower().endswith(".pdf"):
        return jsonify({"error": "Only PDF files are supported"}), 400

    has_logo = "logo" in request.files and request.files["logo"].filename
    position = request.form.get("position", "bottom-right")
    try:
        scale = parse_form_float("scale", 0.25, min_value=0.01, max_value=1.0)
        opacity = parse_form_float("opacity", 0.3, min_value=0.0, max_value=1.0)
        margin = parse_form_float("margin", 30, min_value=0)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    uid = uuid.uuid4().hex[:12]
    input_path = os.path.join(UPLOAD_FOLDER, f"proc_input_{uid}.pdf")
    mid_path = os.path.join(UPLOAD_FOLDER, f"proc_mid_{uid}.pdf")
    output_path = os.path.join(UPLOAD_FOLDER, f"proc_output_{uid}.pdf")
    logo_path = os.path.join(UPLOAD_FOLDER, f"proc_logo_{uid}.tmp")
    sid = get_session_id()
    file_size = 0

    try:
        pdf_file.save(input_path)
        file_size = os.path.getsize(input_path)

        front_file = request.files.get("front_model")
        back_file = request.files.get("back_model")
        front_bytes = front_file.read() if front_file else None
        back_bytes = back_file.read() if back_file else None

        remove_watermark(input_path, mid_path, front_bytes, back_bytes)

        if not os.path.exists(mid_path):
            return jsonify({"error": "Watermark removal failed"}), 500

        src_path = mid_path

        if has_logo:
            logo_file = request.files["logo"]
            logo_ext = os.path.splitext(logo_file.filename)[1].lower()
            if logo_ext not in (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tiff", ".webp"):
                return jsonify({"error": "Logo must be an image (PNG, JPG, BMP, GIF, TIFF, WEBP)"}), 400

            logo_file.save(logo_path)
            logo_img = Image.open(logo_path).convert("RGBA")

            max_dim = 1200
            if max(logo_img.size) > max_dim:
                ratio = max_dim / max(logo_img.size)
                logo_img = logo_img.resize(
                    (int(logo_img.width * ratio), int(logo_img.height * ratio)),
                    Image.LANCZOS,
                )

            if opacity < 1.0:
                alpha = logo_img.split()[3]
                alpha = alpha.point(lambda p: int(p * opacity))
                logo_img.putalpha(alpha)

            rgb_img = logo_img.convert("RGB")
            raw_rgb = rgb_img.tobytes()
            compressed_rgb = zlib.compress(raw_rgb)

            alpha_channel = logo_img.split()[3]
            raw_alpha = alpha_channel.tobytes()
            compressed_alpha = zlib.compress(raw_alpha)

            img_w = rgb_img.width
            img_h = rgb_img.height

            with pikepdf.open(src_path) as pdf:
                for page in pdf.pages:
                    mediabox = page.get("/MediaBox", [0, 0, 612, 792])
                    if isinstance(mediabox, pikepdf.Array):
                        pw = float(mediabox[2]) - float(mediabox[0])
                        ph = float(mediabox[3]) - float(mediabox[1])
                        ox = float(mediabox[0])
                        oy = float(mediabox[1])
                    else:
                        pw, ph, ox, oy = 612, 792, 0, 0

                    lw = pw * scale
                    lh = lw * (img_h / img_w)

                    if position == "top-left":
                        x, y = ox + margin, oy + ph - margin - lh
                    elif position == "top-right":
                        x, y = ox + pw - margin - lw, oy + ph - margin - lh
                    elif position == "bottom-left":
                        x, y = ox + margin, oy + margin
                    elif position == "center":
                        x, y = ox + (pw - lw) / 2, oy + (ph - lh) / 2
                    else:
                        x, y = ox + pw - margin - lw, oy + margin

                    logo_stream = pikepdf.Stream(
                        pdf, compressed_rgb,
                        {
                            "/Type": pikepdf.Name("/XObject"),
                            "/Subtype": pikepdf.Name("/Image"),
                            "/Width": img_w, "/Height": img_h,
                            "/ColorSpace": pikepdf.Name("/DeviceRGB"),
                            "/BitsPerComponent": 8,
                            "/Filter": pikepdf.Name("/FlateDecode"),
                        },
                    )

                    smask = pikepdf.Stream(
                        pdf, compressed_alpha,
                        {
                            "/Type": pikepdf.Name("/XObject"),
                            "/Subtype": pikepdf.Name("/Image"),
                            "/Width": img_w, "/Height": img_h,
                            "/ColorSpace": pikepdf.Name("/DeviceGray"),
                            "/BitsPerComponent": 8,
                            "/Filter": pikepdf.Name("/FlateDecode"),
                        },
                    )
                    logo_stream[pikepdf.Name("/SMask")] = smask

                    res = page.get("/Resources")
                    if res is None:
                        res = pikepdf.Dictionary()
                        page[pikepdf.Name("/Resources")] = res
                    xobj_dict = res.get("/XObject")
                    if xobj_dict is None:
                        xobj_dict = pikepdf.Dictionary()
                        res[pikepdf.Name("/XObject")] = xobj_dict
                    xobj_dict[pikepdf.Name("/LogoStamp")] = logo_stream

                    draw = f"q\n{lw:.2f} 0 0 {lh:.2f} {x:.2f} {y:.2f} cm\n/LogoStamp Do\nQ\n".encode()
                    contents = page.get("/Contents")
                    if contents is None:
                        page[pikepdf.Name("/Contents")] = pikepdf.Stream(pdf, draw)
                    elif isinstance(contents, pikepdf.Array):
                        contents.insert(0, pikepdf.Stream(pdf, draw))
                    else:
                        existing = contents.read_bytes()
                        page[pikepdf.Name("/Contents")] = pikepdf.Stream(pdf, draw + b"\n" + existing)

                pdf.save(output_path)
                src_path = output_path

        if not has_logo:
            import shutil
            shutil.copy2(mid_path, output_path)

        if not os.path.exists(output_path):
            return jsonify({"error": "Processing failed: no output generated"}), 500

        base = os.path.splitext(pdf_file.filename)[0]
        dl_name = f"{base}_clean.pdf" if not has_logo else f"{base}_clean_branded.pdf"

        posthog.capture("pdf_process_success", distinct_id=sid, properties={"mode": "process", "has_logo": bool(has_logo), "filename": pdf_file.filename})
        record_event("process", session_id=sid, mode="process", filename=pdf_file.filename, file_size=file_size, success=True, has_logo=bool(has_logo))
        return send_file(
            output_path,
            as_attachment=True,
            download_name=dl_name,
            mimetype="application/pdf",
        )
    except pikepdf._core.PasswordError:
        posthog.capture("pdf_process_error", distinct_id=sid, properties={"mode": "process", "reason": "password_protected"})
        record_event("process", session_id=sid, mode="process", filename=pdf_file.filename, file_size=file_size, success=False, error_reason="password_protected")
        return jsonify({"error": "This PDF is password-protected"}), 400
    except Exception as e:
        log.error(f"Process error: {traceback.format_exc()}")
        posthog.capture("pdf_process_error", distinct_id=sid, properties={"mode": "process", "reason": str(e)})
        record_event("process", session_id=sid, mode="process", filename=pdf_file.filename, file_size=file_size, success=False, error_reason=str(e))
        return jsonify({"error": f"Error: {str(e)}"}), 500
    finally:
        for p in (input_path, mid_path, output_path, logo_path):
            try:
                if os.path.exists(p):
                    os.remove(p)
            except Exception:
                pass


@app.route("/api/stamp", methods=["POST"])
def handle_stamp():
    pdf_file = request.files.get("file")
    logo_file = request.files.get("logo")

    if not pdf_file:
        return jsonify({"error": "No PDF uploaded"}), 400
    if not logo_file:
        return jsonify({"error": "No logo uploaded"}), 400

    if not pdf_file.filename.lower().endswith(".pdf"):
        return jsonify({"error": "Only PDF files are supported"}), 400

    logo_ext = os.path.splitext(logo_file.filename)[1].lower()
    if logo_ext not in (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tiff", ".webp"):
        return jsonify({"error": "Logo must be an image (PNG, JPG, BMP, GIF, TIFF, WEBP)"}), 400

    position = request.form.get("position", "bottom-right")
    try:
        scale = parse_form_float("scale", 0.25, min_value=0.01, max_value=1.0)
        opacity = parse_form_float("opacity", 0.3, min_value=0.0, max_value=1.0)
        margin = parse_form_float("margin", 30, min_value=0)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    uid = uuid.uuid4().hex[:12]
    input_path = os.path.join(UPLOAD_FOLDER, f"stamp_input_{uid}.pdf")
    output_path = os.path.join(UPLOAD_FOLDER, f"stamp_output_{uid}.pdf")
    logo_path = os.path.join(UPLOAD_FOLDER, f"logo_{uid}{logo_ext}")
    sid = get_session_id()
    file_size = 0

    try:
        pdf_file.save(input_path)
        logo_file.save(logo_path)
        file_size = os.path.getsize(input_path)

        logo_img = Image.open(logo_path).convert("RGBA")

        max_dim = 1200
        if max(logo_img.size) > max_dim:
            ratio = max_dim / max(logo_img.size)
            logo_img = logo_img.resize(
                (int(logo_img.width * ratio), int(logo_img.height * ratio)),
                Image.LANCZOS,
            )

        if opacity < 1.0:
            alpha = logo_img.split()[3]
            alpha = alpha.point(lambda p: int(p * opacity))
            logo_img.putalpha(alpha)

        with pikepdf.open(input_path) as pdf:
            for page in pdf.pages:
                mediabox = page.get("/MediaBox", [0, 0, 612, 792])
                if isinstance(mediabox, pikepdf.Array):
                    page_w = float(mediabox[2]) - float(mediabox[0])
                    page_h = float(mediabox[3]) - float(mediabox[1])
                    offset_x = float(mediabox[0])
                    offset_y = float(mediabox[1])
                else:
                    page_w = 612
                    page_h = 792
                    offset_x = 0
                    offset_y = 0

                logo_w = page_w * scale
                logo_h = logo_w * (logo_img.height / logo_img.width)

                margin_x = margin
                margin_y = margin

                if position == "top-left":
                    x = offset_x + margin_x
                    y = offset_y + page_h - margin_y - logo_h
                elif position == "top-right":
                    x = offset_x + page_w - margin_x - logo_w
                    y = offset_y + page_h - margin_y - logo_h
                elif position == "bottom-left":
                    x = offset_x + margin_x
                    y = offset_y + margin_y
                elif position == "center":
                    x = offset_x + (page_w - logo_w) / 2
                    y = offset_y + (page_h - logo_h) / 2
                else:  # bottom-right
                    x = offset_x + page_w - margin_x - logo_w
                    y = offset_y + margin_y

                rgb_img = logo_img.convert("RGB")
                raw_rgb = rgb_img.tobytes()
                compressed_rgb = zlib.compress(raw_rgb)

                logo_pdf_image = pikepdf.Stream(
                    pdf,
                    compressed_rgb,
                    {
                        "/Type": pikepdf.Name("/XObject"),
                        "/Subtype": pikepdf.Name("/Image"),
                        "/Width": rgb_img.width,
                        "/Height": rgb_img.height,
                        "/ColorSpace": pikepdf.Name("/DeviceRGB"),
                        "/BitsPerComponent": 8,
                        "/Filter": pikepdf.Name("/FlateDecode"),
                    },
                )

                alpha_channel = logo_img.split()[3]
                raw_alpha = alpha_channel.tobytes()
                compressed_alpha = zlib.compress(raw_alpha)

                smask_stream = pikepdf.Stream(
                    pdf,
                    compressed_alpha,
                    {
                        "/Type": pikepdf.Name("/XObject"),
                        "/Subtype": pikepdf.Name("/Image"),
                        "/Width": alpha_channel.width,
                        "/Height": alpha_channel.height,
                        "/ColorSpace": pikepdf.Name("/DeviceGray"),
                        "/BitsPerComponent": 8,
                        "/Filter": pikepdf.Name("/FlateDecode"),
                    },
                )

                logo_pdf_image[pikepdf.Name("/SMask")] = smask_stream

                xobject_name = pikepdf.Name("/LogoStamp")
                res = page.get("/Resources")
                if res is None:
                    res = pikepdf.Dictionary()
                    page[pikepdf.Name("/Resources")] = res

                xobj_dict = res.get("/XObject")
                if xobj_dict is None:
                    xobj_dict = pikepdf.Dictionary()
                    res[pikepdf.Name("/XObject")] = xobj_dict

                xobj_dict[xobject_name] = logo_pdf_image

                draw_cmd = (
                    f"q\n"
                    f"{logo_w:.2f} 0 0 {logo_h:.2f} {x:.2f} {y:.2f} cm\n"
                    f"/LogoStamp Do\n"
                    f"Q\n"
                ).encode()

                contents = page.get("/Contents")
                if contents is None:
                    new_stream = pikepdf.Stream(pdf, draw_cmd)
                    page[pikepdf.Name("/Contents")] = new_stream
                elif isinstance(contents, pikepdf.Array):
                    contents.insert(0, pikepdf.Stream(pdf, draw_cmd))
                else:
                    existing = contents.read_bytes()
                    new_stream = pikepdf.Stream(pdf, draw_cmd + b"\n" + existing)
                    page[pikepdf.Name("/Contents")] = new_stream

            pdf.save(output_path)

        if not os.path.exists(output_path):
            return jsonify({"error": "Stamping failed: no output generated"}), 500

        posthog.capture("pdf_process_success", distinct_id=sid, properties={"mode": "stamp", "filename": pdf_file.filename, "position": position})
        record_event("process", session_id=sid, mode="stamp", filename=pdf_file.filename, file_size=file_size, success=True, has_logo=True, position=position)
        return send_file(
            output_path,
            as_attachment=True,
            download_name=f"stamped_{pdf_file.filename}",
            mimetype="application/pdf",
        )
    except pikepdf._core.PasswordError:
        posthog.capture("pdf_process_error", distinct_id=sid, properties={"mode": "stamp", "reason": "password_protected"})
        record_event("process", session_id=sid, mode="stamp", filename=pdf_file.filename, file_size=file_size, success=False, error_reason="password_protected")
        return jsonify({"error": "This PDF is password-protected"}), 400
    except Exception as e:
        log.error(f"Stamp error: {traceback.format_exc()}")
        posthog.capture("pdf_process_error", distinct_id=sid, properties={"mode": "stamp", "reason": str(e)})
        record_event("process", session_id=sid, mode="stamp", filename=pdf_file.filename, file_size=file_size, success=False, error_reason=str(e))
        return jsonify({"error": f"Error stamping PDF: {str(e)}"}), 500
    finally:
        for p in (input_path, output_path, logo_path):
            try:
                if os.path.exists(p):
                    os.remove(p)
            except Exception:
                pass


_AI_STUDIO_OUTPUT = os.path.join(BASE_DIR, "static", "ai-studio-generated")

def _ais_build_prompts(data):
    def clean(key, fallback=""):
        return (data.get(key) or "").strip() or fallback

    name    = clean("productName", "Annie Dress")
    details = clean("dressDetails", "sewing pattern dress")
    studio  = clean("studioBackground", "solid warm beige background, seamless")
    palette = clean("colors", "sage green, ivory, dusty rose, golden mustard, lavender, powder blue")
    man     = clean("maleOutfit", "ivory linen shirt and beige linen trousers")
    common  = (
        f"Use the 2 uploaded images as reference for the same {name} garment style. "
        f"Preserve the sewing pattern and construction: {details}. "
        f"Photorealistic fashion catalog quality, clean lighting, realistic anatomy, "
        f"crisp fabric detail, no text, no logo, no watermark. Background must be {studio}."
    )
    return [
        {"id": "01-front-single",  "title": "Front Single",   "size": "1024x1536",
         "prompt": f"{common} Create one full-body FRONT VIEW image. Use a different adult female model than the references. Change the dress to a new selling-friendly color. The model faces camera in an elegant relaxed catalog pose."},
        {"id": "02-back-single",   "title": "Back Single",    "size": "1024x1536",
         "prompt": f"{common} Create one full-body BACK VIEW image. Use a different adult female model. Change the dress to a new selling-friendly color. Show the back clearly."},
        {"id": "03-front-collage", "title": "Front 6 Models", "size": "1024x1024",
         "prompt": f"{common} Create a 2 rows x 3 columns fashion catalog collage with thin white dividers. Six different adult female models, FRONT VIEW each panel, six colors in order: {palette}. Diverse natural models, polished Etsy listing style."},
        {"id": "04-back-collage",  "title": "Back 6 Models",  "size": "1024x1024",
         "prompt": f"{common} Create a 2 rows x 3 columns fashion catalog collage with thin white dividers. BACK VIEW each panel, same color order: {palette}. Polished Etsy listing style."},
        {"id": "05-couple",        "title": "Couple Image",   "size": "1024x1536",
         "prompt": f"{common} Create one full-body couple fashion catalog image. Female model wears the original {name}. Add a male model beside her wearing {man}. Both stand naturally in a premium summer marketplace pose."},
    ]


@app.route("/api/ai-studio/config", methods=["GET"])
def ai_studio_config():
    """Return non-sensitive config values useful for pre-filling the UI."""
    cfg = _load_woo_config()
    return jsonify({
        "or_key":   cfg.get("openrouter_api_key", ""),
        "or_model": cfg.get("openrouter_model", ""),
    })


@app.route("/api/ai-studio/generate", methods=["POST"])
def ai_studio_generate():
    from openai import OpenAI as _OpenAI
    from io import BytesIO as _BytesIO
    import base64 as _b64

    provider = (request.form.get("provider") or "openai").strip().lower()
    api_key  = (request.form.get("apiKey") or "").strip()
    model    = (request.form.get("model") or "").strip()
    quality  = (request.form.get("quality") or "medium").strip()

    if not api_key:
        return jsonify({"error": "API key required."}), 400

    os.makedirs(_AI_STUDIO_OUTPUT, exist_ok=True)
    prompts = _ais_build_prompts(request.form)
    results = []

    def _clean_err(e):
        """Return a short human-readable error, stripping any HTML blob."""
        msg = str(e)
        if "<" in msg and len(msg) > 200:
            # Likely HTML from a bad API response — extract just the status/code part
            import re as _re
            code = _re.search(r'"code":\s*"?(\w+)"?', msg)
            status = _re.search(r'"status":\s*(\d+)', msg)
            if code:   return f"API error: {code.group(1)}"
            if status: return f"API error: HTTP {status.group(1)}"
            return "API returned an unexpected response (not JSON). Check your API key and model name."
        # Truncate very long messages (e.g. full response dumps)
        if len(msg) > 400:
            return msg[:400] + "…"
        return msg

    try:
        if provider == "openrouter":
            # ── OpenRouter: multimodal image generation via chat/completions ──
            if not model:
                model = "google/gemini-2.5-flash-image"

            client = _OpenAI(
                api_key=api_key,
                base_url="https://openrouter.ai/api/v1",
                default_headers={
                    "HTTP-Referer": "http://localhost:5000",
                    "X-Title": "EtsyLab AI Studio",
                },
            )

            for task in prompts:
                resp = client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": task["prompt"]}],
                    extra_body={"response_format": {"type": "json_object"}} if False else None,
                )
                # Extract image from response — could be base64 URL or external URL in content
                content = resp.choices[0].message.content or ""
                img_data_found = False

                # Try to extract image from structured content (list of parts)
                raw_content = resp.choices[0].message.model_dump().get("content")
                if isinstance(raw_content, list):
                    for part in raw_content:
                        if isinstance(part, dict) and part.get("type") == "image_url":
                            image_url = part.get("image_url", {}).get("url", "")
                            filename = f"{int(time.time())}-{task['id']}.png"
                            filepath = os.path.join(_AI_STUDIO_OUTPUT, filename)
                            if image_url.startswith("data:"):
                                b64 = image_url.split(",", 1)[1]
                                with open(filepath, "wb") as fh:
                                    fh.write(_b64.b64decode(b64))
                            else:
                                r = requests.get(image_url, timeout=60)
                                with open(filepath, "wb") as fh:
                                    fh.write(r.content)
                            results.append({**task, "url": f"/static/ai-studio-generated/{filename}"})
                            img_data_found = True
                            break

                if not img_data_found:
                    # Try to find a URL in text content
                    import re as _re
                    urls = _re.findall(r'https?://\S+\.(?:png|jpg|jpeg|webp)', content)
                    if urls:
                        filename = f"{int(time.time())}-{task['id']}.png"
                        filepath = os.path.join(_AI_STUDIO_OUTPUT, filename)
                        r = requests.get(urls[0], timeout=60)
                        with open(filepath, "wb") as fh:
                            fh.write(r.content)
                        results.append({**task, "url": f"/static/ai-studio-generated/{filename}"})
                    else:
                        raise Exception(f"No image found in OpenRouter response for {task['title']}. Response: {content[:200]}")

        else:
            # ── OpenAI: images.edit with reference images ───────────────
            if not model:
                model = "gpt-image-1"

            files = request.files.getlist("images")
            if len(files) != 2:
                return jsonify({"error": "Upload exactly 2 reference images for OpenAI mode."}), 400

            client = _OpenAI(api_key=api_key)
            image_files = [
                (f.filename or f"image{i}.png", _BytesIO(f.read()), f.mimetype or "image/png")
                for i, f in enumerate(files)
            ]

            for task in prompts:
                resp = client.images.edit(
                    model=model,
                    image=image_files,
                    prompt=task["prompt"],
                    size=task["size"],
                    quality=quality,
                    n=1,
                )
                img_data = resp.data[0]
                filename = f"{int(time.time())}-{task['id']}.png"
                filepath = os.path.join(_AI_STUDIO_OUTPUT, filename)

                if getattr(img_data, "b64_json", None):
                    with open(filepath, "wb") as fh:
                        fh.write(_b64.b64decode(img_data.b64_json))
                elif getattr(img_data, "url", None):
                    r = requests.get(img_data.url, timeout=60)
                    with open(filepath, "wb") as fh:
                        fh.write(r.content)
                else:
                    return jsonify({"error": f"No image data for {task['title']}"}), 500

                results.append({**task, "url": f"/static/ai-studio-generated/{filename}"})

        return jsonify({"results": results})

    except Exception as e:
        log.error(f"AI Studio generate error: {e}")
        return jsonify({"error": _clean_err(e)}), 500


@app.errorhandler(413)
def too_large(e):
    return jsonify({"error": "File too large. Maximum size is 100MB."}), 413


@app.errorhandler(500)
def internal_error(e):
    return jsonify({"error": "Internal server error. Please try again."}), 500


def get_sheets_service():
    sa_path = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not sa_path or not os.path.exists(sa_path):
        return None
    try:
        scopes = ['https://www.googleapis.com/auth/spreadsheets']
        creds = service_account.Credentials.from_service_account_file(sa_path, scopes=scopes)
        return build('sheets', 'v4', credentials=creds)
    except Exception as e:
        log.error(f"Error building sheets service: {str(e)}")
        return None


@app.route("/api/listings", methods=["GET"])
def handle_listings():
    api_key = os.environ.get("GOOGLE_API_KEY")
    sheet_id = os.environ.get("GOOGLE_SHEET_ID")
    tab_name = os.environ.get("GOOGLE_SHEET_TAB", "📋 Listing Tracker")
    
    if not api_key or not sheet_id:
        return jsonify({"error": "Google Sheets configuration missing"}), 500
        
    return fetch_listings_from_sheet(api_key, sheet_id, tab_name)


COLUMN_MAP = {
    "#": "#",
    "Nom du Patron": "Pattern Name",
    "Catégorie": "Category",
    "Sous-catégorie": "Sub Category",
    "Demande": "Demand",
    "Concurrence": "Competition",
    "Unicité": "Uniqueness",
    "Priorité": "Priority",
    "Statut Etsy": "Status",
    "Prix (USD)": "Price",
    "Titre Etsy Suggéré": "Suggested Title (140 chars)",
    "Tags Principaux": "Suggested Tags (all 13)",
    "Notes": "Notes",
    "Dossier Source": "Folder Name",
    "✅ Match": "Match",
    "IndiePattern Titre": "IndiePattern Title",
    "IndiePattern URL": "IndiePattern URL",
    "IndiePattern Description": "IndiePattern Description",
    "IndiePattern Keywords": "IndiePattern Keywords",
    "Statut": "Status",
    "Date Listed": "Date Listed",
}

def fetch_listings_from_sheet(api_key, sheet_id, tab_name):
    # If tab_name is numeric, look up actual sheet name by ID
    if tab_name.isdigit():
        meta_url = f"https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}?key={api_key}"
        try:
            meta_resp = requests.get(meta_url, timeout=15)
            meta = meta_resp.json()
            for s in meta.get('sheets', []):
                if str(s['properties'].get('sheetId')) == tab_name:
                    tab_name = s['properties']['title']
                    break
        except:
            pass
    
    encoded_tab_name = quote(tab_name, safe="")
    url = f"https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}/values/{encoded_tab_name}?key={api_key}"
    try:
        response = requests.get(url, timeout=15)
        data = response.json()
        if "values" not in data:
            return {"listings": [], "total": 0}
            
        rows = data.get("values", [])
        log.info(f"Fetched {len(rows)} rows from sheet. Tab: {tab_name}")
        if not rows:
            return {"listings": [], "total": 0}
            
        headers = rows[0]
        listings = []
        for row in rows[1:]:
            item = {}
            for i, header in enumerate(headers):
                val = row[i] if i < len(row) else ""
                mapped_key = COLUMN_MAP.get(header, header)
                item[mapped_key] = val
            listings.append(item)
        
        return {"listings": listings, "total": len(listings)}
    except Exception as e:
        log.error(f"Error fetching listings: {e}")
        return {"error": str(e), "listings": []}


@app.route("/api/admin/listings", methods=["GET"])
def admin_listings():
    if not check_admin_auth(request):
        return jsonify({"error": "Unauthorized"}), 401
    
    api_key = os.environ.get("GOOGLE_API_KEY")
    sheet_id = os.environ.get("GOOGLE_SHEET_ID")
    tab_name = os.environ.get("GOOGLE_SHEET_TAB", "📋 Listing Tracker")
    
    if not api_key or not sheet_id:
        return jsonify({"error": "Google Sheets configuration missing"}), 500
    
    result = fetch_listings_from_sheet(api_key, sheet_id, tab_name)
    if "error" in result:
        return jsonify(result), 500
    return jsonify(result)


@app.route("/api/calendar", methods=["GET"])
def handle_calendar():
    return handle_listings()


ETSY_SHOP = "PatternsLabCo"
_SCRAPE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Cache-Control": "no-cache",
}


_ETSY_CACHE_FILE = os.path.join(BASE_DIR, "etsy_cache.json")


def _load_etsy_cache():
    try:
        if os.path.exists(_ETSY_CACHE_FILE):
            with open(_ETSY_CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return None


@app.route("/api/analytics/etsy-scrape", methods=["GET"])
def etsy_scrape():
    """Return cached Etsy data (populated via POST /api/analytics/etsy-scrape)."""
    cached = _load_etsy_cache()
    if cached:
        return jsonify(cached)
    return jsonify({"error": "No Etsy data yet — click Sync in the app to scrape your shop."}), 404


@app.route("/api/analytics/etsy-scrape", methods=["POST"])
def etsy_scrape_save():
    """Receive browser-scraped Etsy data and cache it."""
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "No data"}), 400
    data["scraped_at"] = datetime.now(timezone.utc).isoformat()
    try:
        with open(_ETSY_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"ok": True, "listings": len(data.get("listings", []))})


@app.route("/api/analytics/etsy-scrape-old", methods=["GET"])
def etsy_scrape_direct():
    url = f"https://www.etsy.com/shop/{ETSY_SHOP}"
    try:
        if _HAS_CURL_CFFI:
            resp = cffi_requests.get(url, impersonate="chrome124", timeout=25)
        else:
            scraper = cloudscraper.create_scraper(browser={"browser": "chrome", "platform": "windows", "mobile": False})
            resp = scraper.get(url, timeout=25)
        resp.raise_for_status()
    except Exception as e:
        return jsonify({"error": f"Could not reach Etsy: {e}"}), 502

    soup = BeautifulSoup(resp.text, "html.parser")
    text = soup.get_text(" ", strip=True)

    # ── Shop stats ────────────────────────────────────────────────
    import re as _re
    def _int(pattern, src, default=0):
        m = _re.search(pattern, src, _re.IGNORECASE)
        return int(m.group(1).replace(",", "")) if m else default

    total_items = _int(r"Search all ([\d,]+) items?", text) or \
                  _int(r"All\s+([\d,]+)", text)
    sales       = _int(r"([\d,]+)\s+sales?", text)
    reviews     = _int(r"([\d,]+)\s+(?:review|sale)s?.*?Star", text)
    admirers    = _int(r"([\d,]+)\s+[Aa]dmirers?", text)

    # ── Listing cards ─────────────────────────────────────────────
    seen = set()
    listings = []
    for card in soup.select(".v2-listing-card, li[data-listing-id]"):
        link_tag = card.find("a", href=_re.compile(r"/listing/\d+"))
        href = link_tag["href"].split("?")[0] if link_tag else None
        if href in seen:
            continue
        if href:
            seen.add(href)

        title_tag = card.find("h3") or card.find(class_=_re.compile(r"listing-card.*title|v2-listing-card__title"))
        price_val = card.find(class_="currency-value")
        price_sym = card.find(class_="currency-symbol")
        img_tag   = card.find("img")

        listing_id_match = _re.search(r"/listing/(\d+)", href or "")
        fav_tag = card.find(attrs={"data-wishlist-count": True})

        listings.append({
            "id":        listing_id_match.group(1) if listing_id_match else None,
            "title":     title_tag.get_text(strip=True) if title_tag else None,
            "price":     ((price_sym.get_text(strip=True) if price_sym else "") +
                          (price_val.get_text(strip=True) if price_val else "")),
            "url":       href,
            "img":       img_tag.get("src") or img_tag.get("data-src") if img_tag else None,
            "favorites": int(fav_tag["data-wishlist-count"]) if fav_tag else None,
        })

    if not total_items:
        total_items = len(listings)

    return jsonify({
        "shop_name": ETSY_SHOP,
        "shop_url":  url,
        "shop_id":   "65183353",
        "stats": {
            "total_items": total_items,
            "sales":       sales,
            "reviews":     reviews,
            "admirers":    admirers,
        },
        "listings": listings,
    })


def _load_woo_config():
    config_path = os.path.join(BASE_DIR, "woocommerce_auto_save", "config.json")
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


@app.route("/api/analytics/woo", methods=["GET"])
def woo_analytics():
    cfg = _load_woo_config()
    wc_url = cfg.get("wc_url", "").rstrip("/")
    wc_key = cfg.get("wc_key", "")
    wc_secret = cfg.get("wc_secret", "")
    if not wc_url or not wc_key or not wc_secret:
        return jsonify({"error": "WooCommerce credentials not configured"}), 500

    auth = (wc_key, wc_secret)
    base = f"{wc_url}/wp-json/wc/v3"
    out = {"store_url": wc_url}

    try:
        # Product counts
        r = requests.get(f"{base}/products", params={"status": "publish", "per_page": 1}, auth=auth, timeout=15)
        out["published_products"] = int(r.headers.get("X-WP-Total", 0))
        r2 = requests.get(f"{base}/products", params={"per_page": 1}, auth=auth, timeout=15)
        out["total_products"] = int(r2.headers.get("X-WP-Total", 0))
        out["draft_products"] = max(0, out["total_products"] - out["published_products"])
    except Exception as e:
        out["products_error"] = str(e)

    try:
        # Sales last 30 days
        date_max = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        date_min = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")
        sr = requests.get(f"{base}/reports/sales", params={"date_min": date_min, "date_max": date_max}, auth=auth, timeout=15)
        sd = sr.json()
        out["sales_30d"] = {
            "total_sales": sd.get("total_sales", "0"),
            "net_sales":   sd.get("net_sales", "0"),
            "total_orders": sd.get("total_orders", 0),
            "total_items":  sd.get("total_items", 0),
        }
    except Exception as e:
        out["sales_error"] = str(e)

    try:
        # Top sellers this month
        tr = requests.get(f"{base}/reports/top_sellers", params={"period": "month"}, auth=auth, timeout=15)
        sellers = tr.json() if tr.ok else []
        out["top_sellers"] = [{"name": s.get("title", ""), "quantity": s.get("quantity", 0), "id": s.get("product_id")} for s in sellers[:6]]
    except Exception as e:
        out["top_sellers_error"] = str(e)

    try:
        # Recent orders
        or_ = requests.get(f"{base}/orders", params={"per_page": 8, "orderby": "date", "order": "desc"}, auth=auth, timeout=15)
        orders = or_.json() if or_.ok else []
        out["recent_orders"] = [{
            "id": o.get("id"),
            "status": o.get("status"),
            "total": o.get("total"),
            "date": (o.get("date_created") or "")[:10],
            "items": len(o.get("line_items", [])),
            "customer": o.get("billing", {}).get("first_name", "Guest"),
        } for o in orders]
    except Exception as e:
        out["orders_error"] = str(e)

    return jsonify(out)


@app.route("/api/analytics/etsy", methods=["GET"])
def etsy_analytics():
    api_key = os.environ.get("GOOGLE_API_KEY")
    sheet_id = os.environ.get("GOOGLE_SHEET_ID")
    tab_name = os.environ.get("GOOGLE_SHEET_TAB", "📋 Listing Tracker")
    if not api_key or not sheet_id:
        return jsonify({"error": "Google Sheets not configured"}), 500

    result = fetch_listings_from_sheet(api_key, sheet_id, tab_name)
    listings = result.get("listings", [])

    def norm(raw):
        s = (raw or "").lower()
        if ("publié" in s or "publie" in s) and "publier" not in s:
            return "published"
        if "publier" in s or "pending" in s:
            return "pending"
        return "other"

    prio_counts = {"1": 0, "2": 0, "3": 0, "4": 0, "other": 0}
    cat_counts = {}
    published = pending = 0

    for l in listings:
        st = norm(l.get("Status", ""))
        if st == "published":
            published += 1
        elif st == "pending":
            pending += 1

        p = l.get("Priority", "")
        if "1" in p:
            prio_counts["1"] += 1
        elif "2" in p:
            prio_counts["2"] += 1
        elif "3" in p:
            prio_counts["3"] += 1
        elif "4" in p:
            prio_counts["4"] += 1
        else:
            prio_counts["other"] += 1

        cat = (l.get("Category") or "Other").strip()
        cat_counts[cat] = cat_counts.get(cat, 0) + 1

    has_indie = sum(1 for l in listings if l.get("IndiePattern URL") or l.get("IndiePattern Title"))

    return jsonify({
        "total": len(listings),
        "published": published,
        "pending": pending,
        "has_indie_data": has_indie,
        "priority_breakdown": prio_counts,
        "category_breakdown": dict(sorted(cat_counts.items(), key=lambda x: -x[1])),
    })


@app.route("/api/listings/update", methods=["POST"])
def update_listing():
    data = request.get_json(silent=True) or {}
    row_index = data.get("index") # 0-based data index (row 1 is header)
    header = data.get("header")
    value = data.get("value", "")

    if not isinstance(row_index, int) or row_index < 0:
        return jsonify({"error": "index must be a non-negative integer"}), 400
    if not isinstance(header, str) or not header.strip():
        return jsonify({"error": "header is required"}), 400
    if value is None:
        value = ""
    
    sheet_id = os.environ.get("GOOGLE_SHEET_ID")
    tab_name = os.environ.get("GOOGLE_SHEET_TAB", "📋 Listing Tracker")
    
    log.info(f"Update request: Row {row_index}, Col '{header}', Val '{value}'")
    
    service = get_sheets_service()
    if not service or not sheet_id:
        return jsonify({
            "success": True, 
            "message": "Local edit only. persistence requires service-account.json.",
            "warning": "Google Sheets persistence is not fully configured."
        })

    try:
        # 1. Find column index for header
        res = service.spreadsheets().values().get(
            spreadsheetId=sheet_id, range=f"'{tab_name}'!1:1"
        ).execute()
        headers = res.get('values', [[]])[0]
        try:
            col_idx = headers.index(header)
        except ValueError:
            # Column not found, attempt to add it to the header row automatically
            log.info(f"Column '{header}' not found in sheet. Adding it to header row.")
            headers.append(header)
            service.spreadsheets().values().update(
                spreadsheetId=sheet_id,
                range=f"'{tab_name}'!1:1",
                valueInputOption="USER_ENTERED",
                body={"values": [headers]}
            ).execute()
            col_idx = len(headers) - 1
            
        # 2. Convert column index to A1 notation (e.g. 0 -> A, 1 -> B, ...)
        col_letter = ""
        n = col_idx + 1
        while n > 0:
            n, rem = divmod(n - 1, 26)
            col_letter = chr(65 + rem) + col_letter
            
        # 3. Update the specific cell (Row index is data index + 2 because of 1-based sheet and header)
        sheet_row = row_index + 2
        cell_range = f"'{tab_name}'!{col_letter}{sheet_row}"
        
        service.spreadsheets().values().update(
            spreadsheetId=sheet_id,
            range=cell_range,
            valueInputOption="USER_ENTERED",
            body={"values": [[value]]}
        ).execute()
        
        return jsonify({"success": True, "message": "Updated Google Sheets successfully"})
    except Exception as e:
        log.error(f"Persistence error: {traceback.format_exc()}")
        return jsonify({"error": f"Failed to persist: {str(e)}"}), 500


ETSY_IMAGE_CACHE = {}

_pw_playwright = None
_pw_browser = None
_pw_lock = __import__('threading').Lock()


def _get_etsy_image_pw(url):
    global _pw_playwright, _pw_browser
    from playwright.sync_api import sync_playwright
    with _pw_lock:
        if _pw_playwright is None:
            _pw_playwright = sync_playwright().start()
        if _pw_browser is None or not _pw_browser.is_connected():
            _pw_browser = _pw_playwright.chromium.launch(
                headless=False,
                args=['--disable-blink-features=AutomationControlled']
            )
    try:
        ctx = _pw_browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
            viewport={'width': 1280, 'height': 800},
        )
        pg = ctx.new_page()
        pg.add_init_script('Object.defineProperty(navigator, "webdriver", {get: () => undefined})')
        pg.goto(url, wait_until='commit', timeout=30000)
        try:
            pg.wait_for_function('document.querySelector(\'meta[property="og:image"]\')', timeout=12000)
            img_url = pg.evaluate('document.querySelector(\'meta[property="og:image"]\')?.content')
        except Exception:
            img_url = pg.evaluate('document.querySelector(\'meta[property="og:image"]\')?.content')
        pg.close()
        ctx.close()
        return img_url
    except Exception as e:
        log.error(f"Playwright error: {str(e)}")
        try:
            ctx.close()
        except Exception:
            pass
        return None


_pw_semaphore = __import__('threading').Semaphore(2)

@app.route("/api/scrape-etsy-image", methods=["GET"])
def scrape_etsy_image():
    url = request.args.get("url")
    if not url or "etsy.com" not in url:
        return jsonify({"error": "Invalid URL"}), 400

    if url in ETSY_IMAGE_CACHE:
        cached_data = ETSY_IMAGE_CACHE[url]
        if time.time() - cached_data['ts'] < 86400:
            return jsonify({"image": cached_data['image']})

    listing_id = None
    parts = url.split("/listing/")
    if len(parts) > 1:
        listing_id = parts[1].split("/")[0].split("?")[0]

    api_key = os.environ.get("ETSY_API_KEY")
    if api_key and listing_id:
        try:
            log.info(f"Trying Etsy API (v3) for listing {listing_id}")
            api_url = f"https://openapi.etsy.com/v3/application/listings/{listing_id}/images"
            res = requests.get(api_url, headers={"x-api-key": api_key}, timeout=5)
            if res.status_code == 200:
                img_data = res.json()
                if img_data.get("results") and len(img_data["results"]) > 0:
                    img_url = img_data["results"][0].get("url_fullxfull") or img_data["results"][0].get("url_570xN")
                    if img_url:
                        ETSY_IMAGE_CACHE[url] = {"image": img_url, "ts": time.time()}
                        return jsonify({"image": img_url})
            log.warning(f"Etsy API v3 failed for {listing_id}: {res.status_code}")
        except Exception as e:
            log.error(f"Etsy API error: {str(e)}")

    with _pw_semaphore:
        img_url = _get_etsy_image_pw(url)
    if img_url:
        ETSY_IMAGE_CACHE[url] = {"image": img_url, "ts": time.time()}
        return jsonify({"image": img_url})

    if listing_id:
        return jsonify({"listing_id": listing_id, "url": url})

    return jsonify({"error": "Failed to fetch image"}), 404


@app.route('/api/generate-listing-ai', methods=['POST'])
def generate_listing_ai():
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()
    category = (data.get('category') or '').strip()
    style = (data.get('style') or '').strip()

    if not name:
        return jsonify({"error": "name is required"}), 400
    
    api_key = (os.getenv('OPENROUTER_API_KEY') or '').strip()
    model = os.getenv('OPENROUTER_MODEL', 'google/gemini-2.0-flash-001')
    
    # Debug log (masked)
    key_peek = f"{api_key[:8]}...{api_key[-4:]}" if api_key else "None"
    log.info(f"AI Generation using model {model} and key {key_peek}")
    
    if not api_key or 'YOUR_OPENROUTER_API_KEY' in api_key:
        return jsonify({"error": "OpenRouter API Key not configured in .env"}), 400
        
    prompt_path = os.path.join(os.path.dirname(__file__), 'prompts', 'etsy_description.md')
    try:
        with open(prompt_path, encoding="utf-8") as f:
            prompt = f.read().format(name=name, category=category, style=style)
    except FileNotFoundError:
        return jsonify({"error": "AI prompt template is missing"}), 500
    
    try:
        response = requests.post(
            url="https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            },
            data=json.dumps({
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "response_format": {"type": "json_object"}
            }),
            timeout=30
        )
        
        if response.status_code != 200:
            log.error(f"OpenRouter Error: {response.status_code} - {response.text}")
            return jsonify({"error": f"AI API Error: {response.text}"}), response.status_code
            
        result = response.json()
        if 'choices' not in result:
            log.error(f"Unexpected AI response structure: {result}")
            return jsonify({"error": "Unexpected response from AI"}), 500
        ai_content = json.loads(result['choices'][0]['message']['content'])
        return jsonify(ai_content)
        
    except Exception as e:
        log.error(f"AI Generation failed: {str(e)}")
        return jsonify({"error": str(e)}), 500


WOO_CONFIG_FILE = os.path.join(BASE_DIR, "woo_config.json")


class WooCommerceClient:
    def __init__(self, base_url, consumer_key, consumer_secret):
        self.base_url = base_url.rstrip("/")
        self.auth_header = "Basic " + base64.b64encode(
            f"{consumer_key}:{consumer_secret}".encode()
).decode()

    def _request(self, method, endpoint, params=None, json_data=None, timeout=30):
        url = f"{self.base_url}/wp-json/wc/v3{endpoint}"
        headers = {
            "Content-Type": "application/json",
            "Authorization": self.auth_header,
        }
        try:
            resp = requests.request(
                method, url, headers=headers, params=params,
                json=json_data, timeout=timeout,
            )
        except requests.exceptions.ConnectionError:
            return None, {"error": f"Cannot connect to {self.base_url}"}, {}
        except requests.exceptions.Timeout:
            return None, {"error": "Request timed out"}, {}
        except Exception as e:
            return None, {"error": str(e)}, {}

        try:
            body = resp.json()
        except Exception:
            body = {"raw": resp.text}

        wc_headers = {}
        for h in ["X-WP-Total", "X-WP-TotalPages"]:
            v = resp.headers.get(h)
            if v:
                wc_headers[h] = v

        if not resp.ok:
            msg = body.get("message", "") if isinstance(body, dict) else ""
            code = body.get("code", "") if isinstance(body, dict) else ""
            return resp.status_code, {"error": msg or f"WooCommerce error {resp.status_code}", "code": code}, wc_headers

        return resp.status_code, body, wc_headers

    def list_products(self, params=None):
        return self._request("GET", "/products", params=params)

    def get_product(self, product_id):
        return self._request("GET", f"/products/{product_id}")

    def create_product(self, data):
        return self._request("POST", "/products", json_data=data)

    def update_product(self, product_id, data):
        return self._request("PUT", f"/products/{product_id}", json_data=data)

    def delete_product(self, product_id, force=False):
        params = {}
        if force:
            params["force"] = "true"
        return self._request("DELETE", f"/products/{product_id}", params=params)


def get_woo_creds():
    cfg = {}
    if os.path.exists(WOO_CONFIG_FILE):
        try:
            with open(WOO_CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            pass
    return {
        "woo_url": os.environ.get("WC_URL") or cfg.get("woo_url", ""),
        "woo_key": os.environ.get("WC_KEY") or cfg.get("woo_key", ""),
        "woo_secret": os.environ.get("WC_SECRET") or cfg.get("woo_secret", ""),
    }


def make_woo_client():
    creds = get_woo_creds()
    if not creds["woo_url"] or not creds["woo_key"] or not creds["woo_secret"]:
        return None, {"error": "WooCommerce credentials not configured. Set WC_URL, WC_KEY, WC_SECRET in .env or save via /api/woo/config."}
    return WooCommerceClient(creds["woo_url"], creds["woo_key"], creds["woo_secret"]), None


@app.route("/api/woo/config", methods=["GET"])
def woo_config_get():
    creds = get_woo_creds()
    masked = {**creds}
    if masked["woo_key"]:
        k = masked["woo_key"]
        masked["woo_key"] = k[:4] + "*" * min(len(k) - 4, 12) if len(k) > 4 else "****"
    if masked["woo_secret"]:
        s = masked["woo_secret"]
        masked["woo_secret"] = s[:4] + "*" * min(len(s) - 4, 20) if len(s) > 4 else "****"
    return jsonify(masked)


@app.route("/api/woo/config", methods=["POST"])
def woo_config_save():
    if not check_admin_auth(request):
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json(silent=True) or {}
    woo_url = (data.get("woo_url") or "").strip().rstrip("/")
    woo_key = (data.get("woo_key") or "").strip()
    woo_secret = (data.get("woo_secret") or "").strip()
    if not woo_url or not woo_key or not woo_secret:
        return jsonify({"error": "All fields required: woo_url, woo_key, woo_secret"}), 400
    cfg = {"woo_url": woo_url, "woo_key": woo_key, "woo_secret": woo_secret}
    try:
        with open(WOO_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except Exception as e:
        return jsonify({"error": f"Failed to save config: {str(e)}"}), 500
    return jsonify({"success": True})


@app.route("/api/woo/products", methods=["GET"])
def woo_products_list():
    if not check_admin_auth(request):
        return jsonify({"error": "Unauthorized"}), 401
    client, err = make_woo_client()
    if err:
        return jsonify(err), 422
    allowed_params = ["search", "per_page", "page", "status", "category", "sku",
                      "orderby", "order", "type", "stock_status", "min_price", "max_price",
                      "after", "before", "exclude", "include", "parent", "slug", "featured"]
    params = {}
    for p in allowed_params:
        val = request.args.get(p)
        if val is not None:
            params[p] = val
    status_code, body, wc_headers = client.list_products(params=params or None)
    if isinstance(body, dict) and "error" in body:
        return jsonify(body), status_code if isinstance(status_code, int) else 502
    resp = make_response(jsonify(body), status_code if isinstance(status_code, int) else 200)
    for h, v in wc_headers.items():
        resp.headers[h] = v
    return resp


@app.route("/api/woo/products/<int:product_id>", methods=["GET"])
def woo_products_get(product_id):
    if not check_admin_auth(request):
        return jsonify({"error": "Unauthorized"}), 401
    client, err = make_woo_client()
    if err:
        return jsonify(err), 422
    status_code, body, wc_headers = client.get_product(product_id)
    if isinstance(body, dict) and "error" in body:
        return jsonify(body), status_code if isinstance(status_code, int) else 502
    resp = make_response(jsonify(body), status_code if isinstance(status_code, int) else 200)
    for h, v in wc_headers.items():
        resp.headers[h] = v
    return resp


@app.route("/api/woo/products", methods=["POST"])
def woo_products_create():
    if not check_admin_auth(request):
        return jsonify({"error": "Unauthorized"}), 401
    client, err = make_woo_client()
    if err:
        return jsonify(err), 422
    data = request.get_json(silent=True) or {}
    payload = {}
    for field in ["name", "type", "status", "featured", "catalog_visibility",
                   "description", "short_description", "sku", "regular_price",
                   "sale_price", "manage_stock", "stock_quantity", "stock_status",
                   "weight", "dimensions", "shipping_class", "virtual", "downloadable",
                   "download_limit", "download_expiry", "tax_status", "tax_class",
                   "meta_data", "categories", "tags", "images"]:
        if field in data:
            payload[field] = data[field]
    if "name" not in payload:
        return jsonify({"error": "name is required"}), 400
    if "regular_price" in payload:
        payload["regular_price"] = str(payload["regular_price"])
    status_code, body, wc_headers = client.create_product(payload)
    if isinstance(body, dict) and "error" in body:
        return jsonify(body), status_code if isinstance(status_code, int) else 502
    record_event("woo_product_create", mode="woo", success=True)
    return jsonify(body), status_code if isinstance(status_code, int) else 201


@app.route("/api/woo/products/<int:product_id>", methods=["PUT"])
def woo_products_update(product_id):
    if not check_admin_auth(request):
        return jsonify({"error": "Unauthorized"}), 401
    client, err = make_woo_client()
    if err:
        return jsonify(err), 422
    data = request.get_json(silent=True) or {}
    payload = {}
    for field in ["name", "type", "status", "featured", "catalog_visibility",
                   "description", "short_description", "sku", "regular_price",
                   "sale_price", "manage_stock", "stock_quantity", "stock_status",
                   "weight", "dimensions", "shipping_class", "virtual", "downloadable",
                   "download_limit", "download_expiry", "tax_status", "tax_class",
                   "meta_data", "categories", "tags", "images"]:
        if field in data:
            payload[field] = data[field]
    if "regular_price" in payload:
        payload["regular_price"] = str(payload["regular_price"])
    status_code, body, wc_headers = client.update_product(product_id, payload)
    if isinstance(body, dict) and "error" in body:
        return jsonify(body), status_code if isinstance(status_code, int) else 502
    record_event("woo_product_update", mode="woo", success=True)
    resp = make_response(jsonify(body), status_code if isinstance(status_code, int) else 200)
    for h, v in wc_headers.items():
        resp.headers[h] = v
    return resp


@app.route("/api/woo/products/<int:product_id>", methods=["DELETE"])
def woo_products_delete(product_id):
    if not check_admin_auth(request):
        return jsonify({"error": "Unauthorized"}), 401
    client, err = make_woo_client()
    if err:
        return jsonify(err), 422
    force = request.args.get("force", "false").lower() == "true"
    status_code, body, wc_headers = client.delete_product(product_id, force=force)
    if isinstance(body, dict) and "error" in body:
        return jsonify(body), status_code if isinstance(status_code, int) else 502
    record_event("woo_product_delete", mode="woo", success=True)
    resp = make_response(jsonify(body), status_code if isinstance(status_code, int) else 200)
    for h, v in wc_headers.items():
        resp.headers[h] = v
    return resp


def _wp_auth_header():
    wp_user = os.environ.get("WP_USERNAME", "")
    wp_pass = os.environ.get("WP_APP_PASSWORD", "").strip()
    if not wp_user or not wp_pass:
        cfg = {}
        if os.path.exists(WOO_CONFIG_FILE):
            try:
                with open(WOO_CONFIG_FILE, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
            except Exception:
                pass
        wp_user = wp_user or cfg.get("wp_username", "")
        wp_pass = wp_pass or cfg.get("wp_app_password", "").strip()
    if not wp_user or not wp_pass:
        return None
    return "Basic " + base64.b64encode(f"{wp_user}:{wp_pass}".encode()).decode()


@app.route("/api/woo/categories", methods=["GET"])
def woo_categories():
    if not check_admin_auth(request):
        return jsonify({"error": "Unauthorized"}), 401
    client, err = make_woo_client()
    if err:
        return jsonify(err), 422
    all_cats = []
    page = 1
    while True:
        status_code, body, wc_headers = client._request("GET", "/products/categories", params={"per_page": "100", "page": str(page)})
        if isinstance(body, dict) and "error" in body:
            return jsonify(body), status_code if isinstance(status_code, int) else 502
        if not isinstance(body, list) or len(body) == 0:
            break
        for c in body:
            all_cats.append({"id": c.get("id"), "name": c.get("name", ""), "slug": c.get("slug", ""), "count": c.get("count", 0), "parent": c.get("parent", 0)})
        if len(body) < 100:
            break
        page += 1
    return jsonify(all_cats)


@app.route("/api/woo/media", methods=["POST"])
def woo_upload_media():
    if not check_admin_auth(request):
        return jsonify({"error": "Unauthorized"}), 401
    auth = _wp_auth_header()
    if not auth:
        return jsonify({"error": "WordPress credentials not configured. Set WP_USERNAME and WP_APP_PASSWORD in .env."}), 422
    creds = get_woo_creds()
    store_url = creds["woo_url"].rstrip("/")
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "No file selected"}), 400
    mime_type = f.mimetype or "application/octet-stream"
    try:
        file_bytes = f.read()
    except Exception as e:
        return jsonify({"error": f"Failed to read file: {str(e)}"}), 400
    url = f"{store_url}/wp-json/wp/v2/media"
    headers = {
        "Authorization": auth,
        "Content-Disposition": f'attachment; filename="{f.filename}"',
        "Content-Type": mime_type,
    }
    try:
        resp = requests.post(url, headers=headers, data=file_bytes, timeout=120)
    except requests.exceptions.ConnectionError:
        return jsonify({"error": f"Cannot connect to {store_url}"}), 502
    except requests.exceptions.Timeout:
        return jsonify({"error": "Upload timed out"}), 504
    except Exception as e:
        return jsonify({"error": str(e)}), 502
    if resp.status_code == 401:
        return jsonify({"error": "WordPress rejected credentials (401). Check WP_USERNAME and WP_APP_PASSWORD in .env."}), 401
    if resp.status_code >= 400:
        try:
            err_data = resp.json()
            return jsonify({"error": err_data.get("message", f"Upload failed with status {resp.status_code}")}), resp.status_code
        except Exception:
            return jsonify({"error": f"Upload failed with status {resp.status_code}"}), resp.status_code
    data = resp.json()
    return jsonify({"id": data.get("id"), "source_url": data.get("source_url", ""), "title": data.get("title", {}).get("rendered", ""), "media_type": data.get("media_type", "")}), 201


@app.route("/api/woo/generate", methods=["POST"])
def woo_ai_generate():
    if not check_admin_auth(request):
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json(silent=True) or {}
    pdf_text = (data.get("pdf_text") or "").strip()
    filename = (data.get("filename") or "").strip()
    product_name = (data.get("product_name") or "").strip()
    if not pdf_text and not product_name:
        return jsonify({"error": "Provide pdf_text or product_name"}), 400
    api_key = (os.getenv("OPENROUTER_API_KEY") or "").strip()
    model = os.getenv("OPENROUTER_MODEL", "google/gemini-2.0-flash-001")
    if not api_key or "YOUR_OPENROUTER_API_KEY" in api_key:
        return jsonify({"error": "OpenRouter API Key not configured in .env"}), 400
    system_prompt = "You are an expert product copywriter for a sewing pattern store. The store sells digital PDF sewing patterns for garments, accessories, and home decor. Customers are home sewists ranging from beginners to advanced. All your output must be accurate, SEO-friendly, and written in an engaging tone. When writing HTML descriptions, use <p>, <ul>, <li>, <strong> tags only — no headings or inline styles."
    client, wc_err = make_woo_client()
    categories = []
    if not wc_err:
        _, cat_body, _ = client._request("GET", "/products/categories", params={"per_page": "100"})
        if isinstance(cat_body, list):
            categories = [{"id": c.get("id"), "name": c.get("name", "")} for c in cat_body]
    try:
        import openai
        oai_client = openai.OpenAI(api_key=api_key, base_url="https://openrouter.ai/api/v1")
        if not product_name:
            name_prompt = f'Based on this sewing pattern PDF content, generate a concise, SEO-friendly product name.\nThe name should clearly describe the garment/item, include sizing if mentioned, and be suitable as a WooCommerce product title.\nReturn only the product name — no explanation, no quotes.\n\nFilename: {filename}\n\nPDF content:\n{pdf_text[:3000]}'
            name_resp = oai_client.chat.completions.create(model=model, max_tokens=100, messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": name_prompt}])
            product_name = name_resp.choices[0].message.content.strip()
        desc_prompt = f'Write product descriptions for this sewing pattern: "{product_name}"\n\nPDF content:\n{pdf_text[:4000]}\n\nReturn a JSON object with exactly these two keys:\n- "short_description": 1-2 sentences (plain text, max 200 chars) for the WooCommerce excerpt\n- "full_description": 3-5 paragraphs in HTML using only <p>, <ul>, <li>, <strong> tags.\n  Cover: what the pattern makes, skill level, included sizes, suggested fabrics, number of pattern pieces, what\'s included in the PDF.\n\nReturn only valid JSON. No markdown fences.'
        desc_resp = oai_client.chat.completions.create(model=model, max_tokens=1000, messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": desc_prompt}])
        desc_raw = desc_resp.choices[0].message.content.strip()
        import re as _re
        desc_raw = _re.sub(r'^```(?:json)?\s*', '', desc_raw)
        desc_raw = _re.sub(r'\s*```$', '', desc_raw)
        descriptions = json.loads(desc_raw)
        category_id = 0
        if categories:
            cat_list = "\n".join(f"- ID {c['id']}: {c['name']}" for c in categories)
            cat_prompt = f'Select the most appropriate WooCommerce category for this sewing pattern.\n\nProduct name: {product_name}\nPDF excerpt: {pdf_text[:1500]}\n\nAvailable categories:\n{cat_list}\n\nReturn only the numeric category ID — nothing else.'
            cat_resp = oai_client.chat.completions.create(model=model, max_tokens=10, messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": cat_prompt}])
            cat_raw = cat_resp.choices[0].message.content.strip()
            try:
                category_id = int(_re.sub(r'\D', '', cat_raw)) if _re.search(r'\d', cat_raw) else 0
            except ValueError:
                category_id = categories[0]["id"] if categories else 0
        tags_prompt = f'Suggest up to 8 product tags for this sewing pattern: "{product_name}"\n\nPDF excerpt: {pdf_text[:1500]}\n\nTags should cover: garment type, skill level, sizing system, occasion/use, fabric type, style keywords.\nReturn a JSON array of strings — tag names only, lowercase, no explanation.\nExample: ["dress", "beginner", "women", "summer", "wrap dress"]\n\nReturn only valid JSON. No markdown fences.'
        tags_resp = oai_client.chat.completions.create(model=model, max_tokens=150, messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": tags_prompt}])
        tags_raw = tags_resp.choices[0].message.content.strip()
        tags_raw = _re.sub(r'^```(?:json)?\s*', '', tags_raw)
        tags_raw = _re.sub(r'\s*```$', '', tags_raw)
        try:
            tags = json.loads(tags_raw)
            tags = [str(t) for t in tags][:8]
        except (json.JSONDecodeError, TypeError):
            tags = []
        return jsonify({
            "name": product_name,
            "short_description": descriptions.get("short_description", ""),
            "full_description": descriptions.get("full_description", ""),
            "category_id": category_id,
            "tags": tags,
            "categories": categories,
        })
    except json.JSONDecodeError as e:
        return jsonify({"error": f"AI returned invalid JSON: {str(e)}"}), 502
    except Exception as e:
        log.error(f"Woo AI generate error: {traceback.format_exc()}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/woo/products/create-full", methods=["POST"])
def woo_product_create_full():
    if not check_admin_auth(request):
        return jsonify({"error": "Unauthorized"}), 401
    client, err = make_woo_client()
    if err:
        return jsonify(err), 422
    name = (request.form.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name is required"}), 400
    price = request.form.get("regular_price", "0")
    status = request.form.get("status", "draft")
    short_description = request.form.get("short_description", "")
    full_description = request.form.get("description", "")
    sku = request.form.get("sku", "")
    category_id = request.form.get("category_id", "")
    tags_raw = request.form.get("tags", "")
    tags = [t.strip() for t in tags_raw.split(",") if t.strip()] if tags_raw else []
    virtual = request.form.get("virtual", "true").lower() == "true"
    downloadable = request.form.get("downloadable", "true").lower() == "true"
    is_single_pdf = request.form.get("is_single_pdf", "false").lower() == "true"
    folder_path = request.form.get("folder_path", "")
    image_ids = []
    cover_file = request.files.get("cover_image")
    gallery_files = request.files.getlist("gallery_images")
    auth = _wp_auth_header()
    store_url = get_woo_creds()["woo_url"].rstrip("/")
    if (cover_file or gallery_files) and (not auth or not store_url):
        return jsonify({"error": "WordPress credentials required for image uploads. Set WP_USERNAME and WP_APP_PASSWORD."}), 422
    if cover_file:
        try:
            mime = cover_file.mimetype or "image/jpeg"
            file_bytes = cover_file.read()
            url = f"{store_url}/wp-json/wp/v2/media"
            headers = {"Authorization": auth, "Content-Disposition": f'attachment; filename="{cover_file.filename}"', "Content-Type": mime}
            resp = requests.post(url, headers=headers, data=file_bytes, timeout=120)
            if resp.status_code >= 400:
                return jsonify({"error": f"Cover image upload failed: {resp.status_code} {resp.text[:200]}"}), 502
            image_ids.append(resp.json().get("id"))
        except Exception as e:
            return jsonify({"error": f"Cover image upload error: {str(e)}"}), 502
    for gf in gallery_files:
        if not gf or not gf.filename:
            continue
        try:
            mime = gf.mimetype or "image/jpeg"
            file_bytes = gf.read()
            url = f"{store_url}/wp-json/wp/v2/media"
            headers = {"Authorization": auth, "Content-Disposition": f'attachment; filename="{gf.filename}"', "Content-Type": mime}
            resp = requests.post(url, headers=headers, data=file_bytes, timeout=120)
            if resp.status_code >= 400:
                log.warning(f"Gallery image upload failed: {resp.status_code}")
                continue
            image_ids.append(resp.json().get("id"))
        except Exception as e:
            log.warning(f"Gallery image upload error: {str(e)}")
            continue
    downloads = []
    pdf_file = request.files.get("pdf_file")
    pdf_files = request.files.getlist("pdf_files")
    if pdf_file and auth and store_url:
        try:
            file_bytes = pdf_file.read()
            url = f"{store_url}/wp-json/wp/v2/media"
            headers = {"Authorization": auth, "Content-Disposition": f'attachment; filename="{pdf_file.filename}"', "Content-Type": "application/pdf"}
            resp = requests.post(url, headers=headers, data=file_bytes, timeout=120)
            if resp.status_code >= 400:
                log.warning(f"PDF upload failed: {resp.status_code}")
            else:
                downloads.append({"name": pdf_file.filename, "file": resp.json().get("source_url", "")})
        except Exception as e:
            log.warning(f"PDF upload error: {str(e)}")
    for pf in pdf_files:
        if not pf or not pf.filename:
            continue
        if pdf_file and pf.filename == pdf_file.filename:
            continue
        try:
            file_bytes = pf.read()
            url = f"{store_url}/wp-json/wp/v2/media"
            headers = {"Authorization": auth, "Content-Disposition": f'attachment; filename="{pf.filename}"', "Content-Type": "application/pdf"}
            resp = requests.post(url, headers=headers, data=file_bytes, timeout=120)
            if resp.status_code < 400:
                downloads.append({"name": pf.filename, "file": resp.json().get("source_url", "")})
        except Exception as e:
            log.warning(f"PDF upload error for {pf.filename}: {str(e)}")
    if is_single_pdf and folder_path and auth and store_url:
        if os.path.isfile(folder_path) and folder_path.lower().endswith(".pdf"):
            try:
                with open(folder_path, "rb") as fh:
                    file_bytes = fh.read()
                pdf_name = os.path.basename(folder_path)
                url = f"{store_url}/wp-json/wp/v2/media"
                headers = {"Authorization": auth, "Content-Disposition": f'attachment; filename="{pdf_name}"', "Content-Type": "application/pdf"}
                resp = requests.post(url, headers=headers, data=file_bytes, timeout=120)
                if resp.status_code < 400:
                    downloads.append({"name": pdf_name, "file": resp.json().get("source_url", "")})
            except Exception as e:
                log.warning(f"Single PDF upload from folder error: {str(e)}")
    downloads = []
    if download_url:
        downloads = [{"name": pdf_file.filename if pdf_file else (os.path.basename(folder_path) if folder_path else "Pattern PDF"), "file": download_url}]
    payload = {
        "name": name,
        "type": "simple",
        "status": status,
        "virtual": virtual,
        "downloadable": downloadable,
        "regular_price": str(float(price)) if price else "0",
        "short_description": short_description,
        "description": full_description,
    }
    if sku:
        payload["sku"] = sku
    if category_id:
        try:
            payload["categories"] = [{"id": int(category_id)}]
        except ValueError:
            pass
    if tags:
        payload["tags"] = [{"name": t} for t in tags]
    if image_ids:
        payload["images"] = [{"id": iid} for iid in image_ids]
    if downloads:
        payload["downloads"] = downloads
        payload["download_limit"] = -1
        payload["download_expiry"] = -1
    status_code, body, wc_headers = client.create_product(payload)
    if isinstance(body, dict) and "error" in body:
        return jsonify(body), status_code if isinstance(status_code, int) else 502
    record_event("woo_product_create", mode="woo", success=True)
    resp = make_response(jsonify(body), status_code if isinstance(status_code, int) else 201)
    for h, v in wc_headers.items():
        resp.headers[h] = v
    return resp


@app.route("/api/woo/patterns-folder", methods=["GET"])
def woo_patterns_folder_get():
    if not check_admin_auth(request):
        return jsonify({"error": "Unauthorized"}), 401
    cfg = {}
    if os.path.exists(WOO_CONFIG_FILE):
        try:
            with open(WOO_CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            pass
    folder = cfg.get("patterns_folder", "")
    return jsonify({"patterns_folder": folder})


@app.route("/api/woo/patterns-folder", methods=["POST"])
def woo_patterns_folder_set():
    if not check_admin_auth(request):
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json(silent=True) or {}
    folder = (data.get("patterns_folder") or "").strip()
    cfg = {}
    if os.path.exists(WOO_CONFIG_FILE):
        try:
            with open(WOO_CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            pass
    cfg["patterns_folder"] = folder
    try:
        with open(WOO_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except Exception as e:
        return jsonify({"error": f"Failed to save config: {str(e)}"}), 500
    return jsonify({"success": True, "patterns_folder": folder})


@app.route("/api/woo/scan-patterns", methods=["POST"])
def woo_scan_patterns():
    if not check_admin_auth(request):
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json(silent=True) or {}
    folder = data.get("folder", "")
    if not folder:
        cfg = {}
        if os.path.exists(WOO_CONFIG_FILE):
            try:
                with open(WOO_CONFIG_FILE, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
            except Exception:
                pass
        folder = cfg.get("patterns_folder", "")
    if not folder or not os.path.isdir(folder):
        return jsonify({"error": "Patterns folder not found. Set a valid folder path."}), 400
    try:
        import fitz as pdf_module
    except ImportError:
        return jsonify({"error": "PyMuPDF not installed. Run: pip install pymupdf"}), 500
    import re as _re2
    products = []
    try:
        entries = sorted(os.listdir(folder))
    except Exception as e:
        return jsonify({"error": f"Cannot read folder: {str(e)}"}), 400
    subfolders_with_pdfs = []
    direct_pdfs = []
    for entry in entries:
        full_path = os.path.join(folder, entry)
        if os.path.isdir(full_path) and not entry.startswith("_") and not entry.startswith("."):
            pdfs = sorted([f for f in os.listdir(full_path) if f.lower().endswith(".pdf")])
            if pdfs:
                subfolders_with_pdfs.append((entry, full_path, pdfs))
        elif os.path.isfile(full_path) and entry.lower().endswith(".pdf"):
            direct_pdfs.append(entry)
    if subfolders_with_pdfs:
        for entry, full_path, pdfs in subfolders_with_pdfs:
            m = _re2.match(r"^\s*(\d+)\s*[-]?\s*(.*)", entry)
            number = int(m.group(1)) if m else None
            clean_name = (m.group(2).strip() or entry.strip()) if m else entry.strip()
            images = []
            for pdf_name in pdfs:
                try:
                    doc = pdf_module.open(os.path.join(full_path, pdf_name))
                    for page_idx in range(min(len(doc), 4)):
                        page = doc.load_page(page_idx)
                        pix = page.get_pixmap(matrix=pdf_module.Matrix(1.5, 1.5), alpha=False)
                        if pix.width < 200 or pix.height < 200:
                            continue
                        images.append({"pdf": pdf_name, "page": page_idx + 1, "width": pix.width, "height": pix.height})
                    doc.close()
                except Exception:
                    pass
            products.append({
                "folder": entry,
                "path": full_path,
                "number": number,
                "clean_name": clean_name,
                "pdfs": pdfs,
                "image_count": len(images),
                "warnings": [] if len(pdfs) >= 1 else [f"Only {len(pdfs)} PDF(s) found"],
            })
    elif direct_pdfs:
        m = _re2.match(r"^\s*(\d+)\s*[-]?\s*(.*)", os.path.basename(folder))
        base_number = int(m.group(1)) if m else None
        base_clean = (m.group(2).strip() or os.path.basename(folder)) if m else os.path.basename(folder)
        for i, pdf_name in enumerate(direct_pdfs):
            full_path = os.path.join(folder, pdf_name)
            m2 = _re2.match(r"^\s*(\d+)\s*[-]?\s*(.*)", pdf_name)
            number = m2.group(1) if m2 else None
            clean_name = (m2.group(2).strip() or pdf_name) if m2 else pdf_name
            clean_name = os.path.splitext(clean_name)[0]
            images = []
            try:
                doc = pdf_module.open(full_path)
                for page_idx in range(min(len(doc), 4)):
                    page = doc.load_page(page_idx)
                    pix = page.get_pixmap(matrix=pdf_module.Matrix(1.5, 1.5), alpha=False)
                    if pix.width < 200 or pix.height < 200:
                        continue
                    images.append({"pdf": pdf_name, "page": page_idx + 1, "width": pix.width, "height": pix.height})
                doc.close()
            except Exception:
                pass
            products.append({
                "folder": pdf_name,
                "path": full_path,
                "number": number or (base_number + i + 1 if base_number else i + 1),
                "clean_name": clean_name,
                "pdfs": [pdf_name],
                "image_count": len(images),
                "warnings": [],
                "is_single_pdf": True,
            })
    return jsonify({"folder": folder, "products": products, "total": len(products)})


@app.route("/api/woo/scan-pattern-images/<path:folder_path>", methods=["POST"])
def woo_scan_pattern_images(folder_path):
    if not check_admin_auth(request):
        return jsonify({"error": "Unauthorized"}), 401
    import re as _re2
    try:
        import fitz as pdf_module
    except ImportError:
        return jsonify({"error": "PyMuPDF not installed"}), 500
    cfg = {}
    if os.path.exists(WOO_CONFIG_FILE):
        try:
            with open(WOO_CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            pass
    base = cfg.get("patterns_folder", "")
    full_path = folder_path
    if base and not os.path.isabs(folder_path):
        full_path = os.path.join(base, folder_path)
    if not os.path.isdir(full_path):
        return jsonify({"error": f"Folder not found: {full_path}"}), 404
    images = []
    pdfs = sorted([f for f in os.listdir(full_path) if f.lower().endswith(".pdf")])
    for pdf_name in pdfs:
        try:
            doc = pdf_module.open(os.path.join(full_path, pdf_name))
            for page_idx in range(min(len(doc), 8)):
                page = doc.load_page(page_idx)
                pix = page.get_pixmap(matrix=pdf_module.Matrix(2, 2), alpha=False)
                buf = pix.tobytes("jpg")
                img_b64 = base64.b64encode(buf).decode("ascii")
                images.append({
                    "pdf": pdf_name,
                    "page": page_idx + 1,
                    "width": pix.width,
                    "height": pix.height,
                    "thumbnail": f"data:image/jpeg;base64,{img_b64}",
                })
            doc.close()
        except Exception as e:
            images.append({"pdf": pdf_name, "page": 0, "width": 0, "height": 0, "error": str(e)})
    m = _re2.match(r"^\s*(\d+)\s*[-]?\s*(.*)", os.path.basename(full_path))
    clean_name = (m.group(2).strip() or os.path.basename(full_path)) if m else os.path.basename(full_path)
    thumbnail = None
    if images and "thumbnail" in images[0]:
        thumbnail = images[0]["thumbnail"]
    return jsonify({"folder": os.path.basename(full_path), "path": full_path, "clean_name": clean_name, "pdfs": pdfs, "images": images, "thumbnail": thumbnail})


@app.route("/api/woo/upload-pattern", methods=["POST"])
def woo_upload_pattern():
    if not check_admin_auth(request):
        return jsonify({"error": "Unauthorized"}), 401
    client, err = make_woo_client()
    if err:
        return jsonify(err), 422
    name = (request.form.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name is required"}), 400
    price = request.form.get("regular_price", "6.99")
    status = request.form.get("status", "draft")
    short_description = request.form.get("short_description", "")
    full_description = request.form.get("description", "")
    category_id = request.form.get("category_id", "")
    tags_raw = request.form.get("tags", "")
    tags = [t.strip() for t in tags_raw.split(",") if t.strip()] if tags_raw else []
    folder_path = request.form.get("folder_path", "")
    auth = _wp_auth_header()
    store_url = get_woo_creds()["woo_url"].rstrip("/")
    image_ids = []
    cover_file = request.files.get("cover_image")
    if cover_file:
        try:
            mime = cover_file.mimetype or "image/jpeg"
            file_bytes = cover_file.read()
            url = f"{store_url}/wp-json/wp/v2/media"
            headers = {"Authorization": auth, "Content-Disposition": f'attachment; filename="{cover_file.filename}"', "Content-Type": mime}
            resp = requests.post(url, headers=headers, data=file_bytes, timeout=120)
            if resp.status_code < 400:
                image_ids.append(resp.json().get("id"))
        except Exception as e:
            log.warning(f"Cover upload error: {str(e)}")
    gallery_files = request.files.getlist("gallery_images")
    for gf in gallery_files:
        if not gf or not gf.filename:
            continue
        try:
            mime = gf.mimetype or "image/jpeg"
            file_bytes = gf.read()
            url = f"{store_url}/wp-json/wp/v2/media"
            headers = {"Authorization": auth, "Content-Disposition": f'attachment; filename="{gf.filename}"', "Content-Type": mime}
            resp = requests.post(url, headers=headers, data=file_bytes, timeout=120)
            if resp.status_code < 400:
                image_ids.append(resp.json().get("id"))
        except Exception:
            continue
    downloads = []
    pdf_files = request.files.getlist("pdf_files")
    uploaded_pdf_names = set()
    for pf in pdf_files:
        if not pf or not pf.filename:
            continue
        uploaded_pdf_names.add(pf.filename)
        try:
            file_bytes = pf.read()
            url = f"{store_url}/wp-json/wp/v2/media"
            headers = {"Authorization": auth, "Content-Disposition": f'attachment; filename="{pf.filename}"', "Content-Type": "application/pdf"}
            resp = requests.post(url, headers=headers, data=file_bytes, timeout=120)
            if resp.status_code < 400:
                downloads.append({"name": pf.filename, "file": resp.json().get("source_url", "")})
        except Exception:
            continue
    is_single_pdf = request.form.get("is_single_pdf", "false").lower() == "true"
    if folder_path and auth and store_url:
        if is_single_pdf and os.path.isfile(folder_path) and folder_path.lower().endswith(".pdf"):
            pdf_name = os.path.basename(folder_path)
            if pdf_name not in uploaded_pdf_names:
                try:
                    with open(folder_path, "rb") as fh:
                        file_bytes = fh.read()
                    url = f"{store_url}/wp-json/wp/v2/media"
                    headers = {"Authorization": auth, "Content-Disposition": f'attachment; filename="{pdf_name}"', "Content-Type": "application/pdf"}
                    resp = requests.post(url, headers=headers, data=file_bytes, timeout=120)
                    if resp.status_code < 400:
                        downloads.append({"name": pdf_name, "file": resp.json().get("source_url", "")})
                except Exception as e:
                    log.warning(f"Single PDF upload error: {str(e)}")
        elif os.path.isdir(folder_path):
            try:
                import fitz as _fitz
            except ImportError:
                _fitz = None
            for pdf_name in sorted(os.listdir(folder_path)):
                if not pdf_name.lower().endswith(".pdf"):
                    continue
                pdf_full = os.path.join(folder_path, pdf_name)
                if not os.path.isfile(pdf_full) or pdf_name in uploaded_pdf_names:
                    continue
                try:
                    with open(pdf_full, "rb") as fh:
                        file_bytes = fh.read()
                    url = f"{store_url}/wp-json/wp/v2/media"
                    headers = {"Authorization": auth, "Content-Disposition": f'attachment; filename="{pdf_name}"', "Content-Type": "application/pdf"}
                    resp = requests.post(url, headers=headers, data=file_bytes, timeout=120)
                    if resp.status_code < 400:
                        downloads.append({"name": pdf_name, "file": resp.json().get("source_url", "")})
                except Exception as e:
                    log.warning(f"PDF upload from folder error for {pdf_name}: {str(e)}")
            if _fitz and not image_ids and not cover_file:
                try:
                    all_pdfs_in_folder = sorted(
                        [f for f in os.listdir(folder_path) if f.lower().endswith(".pdf")],
                        key=lambda f: f.lower(),
                    )
                    for pdf_name in all_pdfs_in_folder[:1]:
                        doc = _fitz.open(os.path.join(folder_path, pdf_name))
                        for page_idx in range(min(len(doc), 2)):
                            page = doc.load_page(page_idx)
                            pix = page.get_pixmap(matrix=_fitz.Matrix(2, 2), alpha=False)
                            img_bytes = pix.tobytes("jpg")
                            img_name = f"{os.path.splitext(pdf_name)[0]}_p{page_idx+1}.jpg"
                            url = f"{store_url}/wp-json/wp/v2/media"
                            headers = {"Authorization": auth, "Content-Disposition": f'attachment; filename="{img_name}"', "Content-Type": "image/jpeg"}
                            resp = requests.post(url, headers=headers, data=img_bytes, timeout=120)
                            if resp.status_code < 400:
                                image_ids.append(resp.json().get("id"))
                        doc.close()
                        break
                except Exception as e:
                    log.warning(f"Cover extraction from folder error: {str(e)}")
    payload = {
        "name": name,
        "type": "simple",
        "status": status,
        "virtual": True,
        "downloadable": True,
        "regular_price": str(float(price)) if price else "0",
        "short_description": short_description,
        "description": full_description,
    }
    if category_id:
        try:
            payload["categories"] = [{"id": int(category_id)}]
        except ValueError:
            pass
    if tags:
        payload["tags"] = [{"name": t} for t in tags]
    if image_ids:
        payload["images"] = [{"id": iid} for iid in image_ids]
    if downloads:
        payload["downloads"] = downloads
        payload["download_limit"] = -1
        payload["download_expiry"] = -1
    status_code, body, wc_headers = client.create_product(payload)
    if isinstance(body, dict) and "error" in body:
        return jsonify(body), status_code if isinstance(status_code, int) else 502
    record_event("woo_product_create", mode="woo_pattern", success=True)
    resp = make_response(jsonify(body), status_code if isinstance(status_code, int) else 201)
    for h, v in wc_headers.items():
        resp.headers[h] = v
    return resp


if __name__ == "__main__":
    app.run(debug=True, port=5000, use_reloader=False)
