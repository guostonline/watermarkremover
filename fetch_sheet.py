import sys, io, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from google.oauth2 import service_account
from googleapiclient.discovery import build

SCOPES = ['https://www.googleapis.com/auth/spreadsheets.readonly']
creds = service_account.Credentials.from_service_account_file(r'C:\Users\DELL\Dev\watermarkremover\service-account.json', scopes=SCOPES)
service = build('sheets', 'v4', credentials=creds)

sheet_id = '1L6bni_tF_q4qplJeZWLZ59e6qZ_Ds0XlPVkLCRXZglo'
meta = service.spreadsheets().get(spreadsheetId=sheet_id).execute()
sheets = meta.get('sheets', [])
for s in sheets:
    props = s['properties']
    print(f"Sheet: {props['title']} | sheetId: {props.get('sheetId', '')}")

target_title = "🔀 Combined Master"

result = service.spreadsheets().values().get(spreadsheetId=sheet_id, range=target_title).execute()
rows = result.get('values', [])
print(f'Total rows: {len(rows)}')
if rows:
    print(f'Columns: {len(rows[0])}')
    print(f'Header: {json.dumps(rows[0], ensure_ascii=False)}')
    for i in range(1, min(4, len(rows))):
        print(f'Row {i}: {json.dumps(rows[i], ensure_ascii=False)}')

with open(r'C:\Users\DELL\Dev\watermarkremover\listings_sheet_data.json', 'w', encoding='utf-8') as f:
    json.dump(rows, f, ensure_ascii=False, indent=2)
print('Saved to listings_sheet_data.json')