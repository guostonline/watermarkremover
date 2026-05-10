import sys, io, json, requests, time, socket
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', line_buffering=True)
import urllib3.util.connection as urllib3_cn
urllib3_cn.allowed_gai_family = lambda: socket.AF_INET

APPWRITE_ENDPOINT = "https://cloud.appwrite.io/v1"
APPWRITE_PROJECT_ID = "69ef938c001dc44bfe43"
APPWRITE_API_KEY = "standard_342deeafb0dc98a1d7a3a584b35a6ac31ca9babe71351007626f32448bfba8b29dccc360677e628d7c7b19bd1060e3353401591aedb5a4f742c8b1a0066fbf68ae44f247baca0229001ffd37eebaa8e914dd161e7a8b26f7ef675d5eb8d007174e95781376679320d692da57e5b3d7bad2b0bd08f6853299a2b5f6dd707820c2"
HEADERS = {"Content-Type": "application/json", "X-Appwrite-Key": APPWRITE_API_KEY, "X-Appwrite-Project": APPWRITE_PROJECT_ID}
DB_ID = "patternlistings"
COLLECTION_ID = "pattern_manager"

session = requests.Session()
session.headers.update(HEADERS)

with open(r'C:\Users\DELL\Dev\watermarkremover\sheet_data.json', 'r', encoding='utf-8') as f:
    rows = json.load(f)
header = rows[0]
print(f"Loaded {len(rows)-1} rows", flush=True)

ok = 0
skip = 0
fail = 0
for i, row in enumerate(rows[1:], 1):
    def g(col, default=""):
        idx = header.index(col) if col in header else -1
        val = row[idx].strip() if idx >= 0 and idx < len(row) else ""
        return val if val else default

    num_str = g("#")
    try:
        num = int(num_str) if num_str else i
    except:
        num = i

    doc = {
        "num": num,
        "folder_name": g("Nom du Patron"),
        "category": g("Cat\u00e9gorie"),
        "sub_category": g("Sous-cat\u00e9gorie"),
        "demand": g("Demande\n(1-10)"),
        "competition": g("Concurrence\n(1-10)"),
        "uniqueness": g("Unicit\u00e9\n(1-10)"),
        "priority": g("Priorit\u00e9"),
        "status_etsy": g("Statut Etsy"),
        "price_recommended": g("Prix Recommand\u00e9\n(USD)"),
        "price_original": g("Prix Original\n(USD)"),
        "title_etsy": g("Titre Etsy Sugg\u00e9r\u00e9"),
        "tags_main": g("Tags Principaux"),
        "notes": g("Notes / Opportunit\u00e9s"),
        "source_folder": g("Dossier Source"),
    }

    for attempt in range(3):
        try:
            r = session.post(f"{APPWRITE_ENDPOINT}/databases/{DB_ID}/collections/{COLLECTION_ID}/documents",
                json={"documentId": f"pm_{num}", "data": doc, "permissions": []}, timeout=30)
            if r.status_code in (200, 201):
                ok += 1
            elif r.status_code == 409:
                skip += 1
            else:
                fail += 1
                if fail <= 5:
                    print(f"  ERR {num}: {r.json().get('message','')[:100]}", flush=True)
            break
        except Exception as e:
            if attempt < 2:
                time.sleep(2)
            else:
                fail += 1
                print(f"  CONN ERR {num}: {str(e)[:80]}", flush=True)

    if i % 50 == 0:
        print(f"  {i}/{len(rows)-1} ok={ok} skip={skip} fail={fail}", flush=True)
        time.sleep(1)

print(f"\nDone! {ok} inserted, {skip} existed, {fail} failed of {len(rows)-1}", flush=True)