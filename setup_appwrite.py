import sys, io, json, requests, time, socket
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# Force IPv4 to avoid IPv6 issues
import urllib3.util.connection as urllib3_cn
orig_allowed_gai_family = urllib3_cn.allowed_gai_family
def allowed_gai_family():
    return socket.AF_INET
urllib3_cn.allowed_gai_family = allowed_gai_family

APPWRITE_ENDPOINT = "https://cloud.appwrite.io/v1"
APPWRITE_PROJECT_ID = "69ef938c001dc44bfe43"
APPWRITE_API_KEY = "standard_342deeafb0dc98a1d7a3a584b35a6ac31ca9babe71351007626f32448bfba8b29dccc360677e628d7c7b19bd1060e3353401591aedb5a4f742c8b1a0066fbf68ae44f247baca0229001ffd37eebaa8e914dd161e7a8b26f7ef675d5eb8d007174e95781376679320d692da57e5b3d7bad2b0bd08f6853299a2b5f6dd707820c2"

HEADERS = {
    "Content-Type": "application/json",
    "X-Appwrite-Key": APPWRITE_API_KEY,
    "X-Appwrite-Project": APPWRITE_PROJECT_ID,
}

DB_ID = "patternlistings"
COLLECTION_ID = "listings"

# Check attributes status
print("Checking attributes...")
r = requests.get(f"{APPWRITE_ENDPOINT}/databases/{DB_ID}/collections/{COLLECTION_ID}/attributes", headers=HEADERS)
attrs = r.json().get("attributes", [])
for a in attrs:
    status = a.get("status", "unknown")
    key = a.get("key", "")
    required = a.get("required", False)
    print(f"  {key}: status={status}, required={required}, type={a.get('type','')}")

# Check existing documents count
r = requests.get(f"{APPWRITE_ENDPOINT}/databases/{DB_ID}/collections/{COLLECTION_ID}/documents?limit=1", headers=HEADERS)
total = r.json().get("total", 0)
print(f"\nExisting documents: {total}")

# Load data
with open(r'C:\Users\DELL\Dev\watermarkremover\listings_sheet_data.json', 'r', encoding='utf-8') as f:
    rows = json.load(f)

header = rows[0]
print(f"Total rows to insert: {len(rows)-1}")

# Insert documents - use empty string for nullable required fields
ok = 0
fail = 0
for i, row in enumerate(rows[1:], 1):
    def g(col):
        idx = header.index(col) if col in header else -1
        val = row[idx].strip() if idx >= 0 and idx < len(row) else ""
        return val if val else ""

    num_str = g("#")
    try:
        num = int(num_str) if num_str else i
    except:
        num = i

    doc = {
        "num": num,
        "folder_name": g("Ton Pattern (Dossier)") or "Unknown",
        "category": g("Cat\u00e9gorie") or "Uncategorized",
        "sub_category": g("Sous-cat\u00e9gorie") or "",
        "title": g("Titre IndiePattern") or "",
        "url": g("URL IndiePattern") or "",
        "description": g("Description Compl\u00e8te") or "",
        "tags": g("Mots-cl\u00e9s Inclus") or "",
        "status": "",
    }

    r = requests.post(f"{APPWRITE_ENDPOINT}/databases/{DB_ID}/collections/{COLLECTION_ID}/documents",
        headers=HEADERS, json={"documentId": f"listing_{num}", "data": doc, "permissions": []})
    if r.status_code in (200, 201):
        ok += 1
    else:
        fail += 1
        if fail <= 5:
            print(f"  ERR row {i} (num={num}): {r.json().get('message','')[:150]}")

    if i % 20 == 0:
        print(f"  Progress: {i}/{len(rows)-1} (ok={ok}, fail={fail})")

print(f"\nDone! {ok} inserted, {fail} failed out of {len(rows)-1}")