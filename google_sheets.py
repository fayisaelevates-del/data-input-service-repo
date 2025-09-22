"""
Read stops/demands/time-windows from Google Sheets and write `input.json` for the solver.
Expect the sheet to have columns: id,lat,lon,demand,tw_start,tw_end
Uses a service account JSON credentials file whose path is provided via the environment variable `GOOGLE_SERVICE_ACCOUNT`.
"""
import os
import json
from google.oauth2 import service_account
from googleapiclient.discovery import build

SCOPES = ['https://www.googleapis.com/auth/spreadsheets.readonly']


def sheet_to_input(spreadsheet_id: str, range_name: str, out_path: str = 'input.json'):
    cred_path = os.environ.get('GOOGLE_SERVICE_ACCOUNT')
    if not cred_path:
        raise SystemExit('Set GOOGLE_SERVICE_ACCOUNT to the service account JSON path')
    creds = service_account.Credentials.from_service_account_file(cred_path, scopes=SCOPES)
    service = build('sheets', 'v4', credentials=creds)
    sheet = service.spreadsheets()
    result = sheet.values().get(spreadsheetId=spreadsheet_id, range=range_name).execute()
    values = result.get('values', [])
    if not values:
        raise SystemExit('No data found in sheet')
    # assume first row is header
    headers = [h.strip() for h in values[0]]
    rows = []
    for r in values[1:]:
        obj = {headers[i]: r[i] if i < len(r) else '' for i in range(len(headers))}
        rows.append(obj)
    # transform
    stops = []
    demands = []
    tws = []
    for r in rows:
        stops.append((float(r['lat']), float(r['lon'])))
        demands.append(int(r.get('demand') or 0))
        tws.append((int(r.get('tw_start') or 0), int(r.get('tw_end') or 28800)))
    payload = {'stops': stops, 'demands': demands, 'time_windows': tws}
    with open(out_path, 'w') as f:
        json.dump(payload, f, indent=2)
    print('Wrote', out_path)


if __name__ == '__main__':
    import sys
    if len(sys.argv) < 3:
        print('Usage: python google_sheets.py <spreadsheet_id> <range>')
    else:
        sheet_to_input(sys.argv[1], sys.argv[2])
