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
from flask import Flask, request, jsonify, send_file, render_template, Response, make_response
import pikepdf
from PIL import Image
from posthog import Posthog
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

app = Flask(__name__, template_folder="templates", static_folder="static")
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

posthog = Posthog(project_api_key=POSTHOG_KEY, host=POSTHOG_HOST)


def generate_token():
    payload = f"{ADMIN_PASSWORD}:{int(time.time()) // 3600}"
    return hmac.new(payload.encode(), digestmod=hashlib.sha256).hexdigest()[:32]


ADMIN_TOKEN = generate_token()


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
        inv_token = request.cookies.get("invite_token", "") if request else ""
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


def remove_watermark(input_path, output_path):
    with pikepdf.open(input_path) as pdf:
        pages_processed = 0
        wm_oc_names = []

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
        remove_watermark(input_path, output_path)

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
    scale = float(request.form.get("scale", 0.25))
    opacity = float(request.form.get("opacity", 0.3))
    margin = float(request.form.get("margin", 30))

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
        remove_watermark(input_path, mid_path)

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
    scale = float(request.form.get("scale", 0.25))
    opacity = float(request.form.get("opacity", 0.3))
    margin = float(request.form.get("margin", 30))

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


@app.errorhandler(413)
def too_large(e):
    return jsonify({"error": "File too large. Maximum size is 100MB."}), 413


@app.errorhandler(500)
def internal_error(e):
    return jsonify({"error": "Internal server error. Please try again."}), 500


if __name__ == "__main__":
    app.run(debug=True, port=5000)