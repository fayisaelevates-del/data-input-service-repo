import requests
import sqlite3
import json
import time

URL = 'http://127.0.0.1:5000/api/upload_csv'
HEADERS = {'X-API-Token': 'test-token'}

def post_csv(content, geocode=False):
    files = {'file': ('upload.csv', content)}
    data = {}
    if geocode:
        data['geocode'] = '1'
    r = requests.post(URL, files=files, data=data, headers=HEADERS, timeout=30)
    print('POST geocode=%s ->' % geocode, r.status_code, r.text)
    return r

if __name__ == '__main__':
    # Test A: lat/lon CSV
    csv1 = 'lat,lon,label\n32.257254,-110.9723225,Depot\n32.1162014,-111.0419424,Stop B\n'
    post_csv(csv1, geocode=False)
    time.sleep(0.3)

    # Inspect recent trips
    conn = sqlite3.connect('data.db')
    cur = conn.cursor()
    cur.execute("SELECT id, payload FROM trips ORDER BY ROWID DESC LIMIT 10")
    rows = cur.fetchall()
    print('Trips (latest up to 10):')
    for r in rows:
        print(r[0], json.loads(r[1]))
    conn.close()

    # Test B: address-only + geocode
    csv2 = 'address\n1600 Amphitheatre Parkway, Mountain View, CA\n'
    post_csv(csv2, geocode=True)
    # allow a moment for geocode/cache writes
    time.sleep(1.5)

    conn = sqlite3.connect('data.db')
    cur = conn.cursor()
    cur.execute("SELECT query, lat, lon, fetched_at FROM geocode_cache ORDER BY fetched_at DESC LIMIT 5")
    rows = cur.fetchall()
    print('Geocode cache (latest up to 5):')
    for r in rows:
        print(r)
    conn.close()
