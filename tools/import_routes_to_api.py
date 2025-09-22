"""Convert route_vehicle_*.csv files into drivers and trips JSON and POST to local server endpoints.

Usage: run from project root; ensure Flask server is running at http://127.0.0.1:5000/ and set TOKEN env var or edit token variable.
"""
import os
import glob
import csv
import requests

BASE_URL = os.environ.get('ROUTES_BASE_URL', 'http://127.0.0.1:5000')
TOKEN = os.environ.get('SUGGEST_API_TOKEN', '') or ''

def read_route_csv(path):
    rows = []
    with open(path, newline='', encoding='utf-8') as fh:
        rdr = csv.DictReader(fh)
        for r in rdr:
            rows.append(r)
    return rows


def main():
    files = glob.glob('route_vehicle_*.csv')
    drivers = []
    trips = []
    for f in files:
        name = os.path.basename(f)
        # parse vehicle id from filename
        parts = name.replace('.csv','').split('_')
        vid = parts[-1]
        drivers.append({'id': vid, 'lat': 0.0, 'lon': 0.0, 'active': True})
        rows = read_route_csv(f)
        for i, r in enumerate(rows):
            tid = f"{vid}_stop_{i+1}"
            lat = float(r.get('lat') or 0)
            lon = float(r.get('lon') or 0)
            stop_label = r.get('stop') or tid
            trips.append({'id': tid, 'lat': lat, 'lon': lon, 'stop': stop_label, 'service_sec': int(float(r.get('service_sec') or 0)), 'eta_hhmm': r.get('eta_hhmm')})
            # set driver lat/lon to first non-zero stop
            if drivers[-1]['lat'] == 0.0 and lat != 0.0:
                drivers[-1]['lat'] = lat
            if drivers[-1]['lon'] == 0.0 and lon != 0.0:
                drivers[-1]['lon'] = lon

    headers = {'Content-Type':'application/json'}
    if TOKEN:
        headers['X-API-Token'] = TOKEN
    print(f"Posting {len(drivers)} drivers and {len(trips)} trips to {BASE_URL}")
    if drivers:
        resp = requests.post(BASE_URL + '/api/drivers', json={'drivers': drivers}, headers=headers)
        print('drivers ->', resp.status_code, resp.text)
    if trips:
        resp = requests.post(BASE_URL + '/api/trips', json={'trips': trips}, headers=headers)
        print('trips ->', resp.status_code, resp.text)

if __name__ == '__main__':
    main()
