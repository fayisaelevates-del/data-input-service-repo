"""
Post a small Tucson sample to the Flask app at /api/drivers and /api/trips,
then call /api/preview and save the result to preview_sample.json

Usage: python tools/post_preview_sample.py
"""
import json
import time
import requests

URL = 'http://127.0.0.1:5000'
TOKEN = 'preview-token'

drivers = [
    {'id': 'drv-1', 'lat': 32.2226, 'lon': -110.9747, 'active': True},
    {'id': 'drv-2', 'lat': 32.2608, 'lon': -110.9350, 'active': True},
    {'id': 'drv-3', 'lat': 32.1328, 'lon': -110.9474, 'active': True},
]

stops = [
    (32.2226, -110.9747),
    (32.2319, -110.9501),
    (32.2220, -110.9265),
    (32.1916, -110.9265),
    (32.3546, -110.9771),
    (32.1328, -110.9474),
    (32.2390, -110.9550),
    (32.2608, -110.9350),
]
trips = []
for i, (lat, lon) in enumerate(stops[1:], start=1):
    trips.append({'id': f'trip-{i}', 'lat': lat, 'lon': lon, 'label': f'Tucson {i}'})

headers = {'Content-Type': 'application/json', 'X-API-Token': TOKEN}

def post(path, payload):
    url = URL + path
    r = requests.post(url, headers=headers, json=payload, timeout=30)
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, r.text

def main():
    print('Posting drivers...')
    sc, res = post('/api/drivers', {'drivers': drivers})
    print('drivers ->', sc, res)
    time.sleep(0.2)
    print('Posting trips...')
    sc2, res2 = post('/api/trips', {'trips': trips})
    print('trips ->', sc2, res2)
    time.sleep(0.2)
    print('Requesting preview...')
    sc3, res3 = post('/api/preview', {})
    print('preview ->', sc3)
    if sc3 == 200:
        with open('preview_sample.json', 'w') as f:
            json.dump(res3.get('result', res3), f, indent=2)
        print('Saved preview_sample.json')
    else:
        print('Preview failed:', res3)

if __name__ == '__main__':
    main()
