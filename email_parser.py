"""
email_parser.py

Heuristic parser for incoming route emails. It extracts common fields and writes/ appends to
`parsed_routes.csv` which matches the Google Sheets template headers.

Usage:
  python email_parser.py email.txt
  or pipe text via stdin:
  type email.txt | python email_parser.py

Notes:
- This is a heuristic tool; inspect `parsed_routes.csv` and correct addresses/lat-lon if needed.
- If you provide a Google Maps API key in the env var `GOOGLE_MAPS_API_KEY`, the script will try to geocode addresses.
"""

import re
import sys
import csv
import os
from typing import Optional

try:
    import googlemaps
except Exception:
    googlemaps = None
import requests

OUT_CSV = 'parsed_routes.csv'
HEADERS = ['id', 'address', 'miles', 'time_minutes', 'kid_type', 'notes', 'lat', 'lon', 'demand', 'service_time', 'tw_start', 'tw_end']

MILES_RE = re.compile(r"([0-9]+(?:\.[0-9]+)?)\s*(?:miles|mi)", re.IGNORECASE)
TIME_MIN_RE = re.compile(r"([0-9]+)\s*(?:min|mins|minutes)", re.IGNORECASE)
TIME_HM_RE = re.compile(r"(\d{1,2}):(\d{2})")
KID_TYPE_RE = re.compile(r"(kindergarten|kinder|elementary|special|highschool|middle|preschool|kid|child)", re.IGNORECASE)
ADDRESS_LINE_RE = re.compile(r"(?:Address|Addr|Stop|Location)[:\-]?\s*(.+)", re.IGNORECASE)


def geocode_address(addr: str) -> Optional[tuple]:
    key = os.environ.get('GOOGLE_MAPS_API_KEY')
    if not key or not googlemaps:
        # fallback to OpenRouteService if available
        ors = os.environ.get('ORS_API_KEY')
        if not ors:
            return None
        try:
            resp = requests.post('https://api.openrouteservice.org/geocode/search', params={'api_key': ors, 'text': addr}, timeout=10)
            data = resp.json()
            features = data.get('features') or []
            if not features:
                return None
            coords = features[0]['geometry']['coordinates']
            return coords[1], coords[0]
        except Exception:
            return None
    try:
        g = googlemaps.Client(key=key)
        res = g.geocode(addr)
        if not res:
            return None
        loc = res[0]['geometry']['location']
        return loc['lat'], loc['lng']
    except Exception:
        return None


def parse_text(text: str) -> dict:
    out = {'address': '', 'miles': '', 'time_minutes': '', 'kid_type': '', 'notes': ''}
    # find address-like lines
    for line in text.splitlines():
        m = ADDRESS_LINE_RE.search(line)
        if m:
            out['address'] = m.group(1).strip()
            break
    # fallback: try to find a line that looks like an address (has digits and street)
    if not out['address']:
        for line in text.splitlines():
            if re.search(r"\d+\s+\w+\s+(Street|St|Avenue|Ave|Road|Rd|Blvd|Lane|Ln|Drive|Dr)", line, re.IGNORECASE):
                out['address'] = line.strip()
                break
    # miles
    m = MILES_RE.search(text)
    if m:
        out['miles'] = m.group(1)
    # time in minutes
    m = TIME_MIN_RE.search(text)
    if m:
        out['time_minutes'] = m.group(1)
    else:
        m2 = TIME_HM_RE.search(text)
        if m2:
            h = int(m2.group(1))
            mm = int(m2.group(2))
            out['time_minutes'] = str(h * 60 + mm)
    # kid type
    m = KID_TYPE_RE.search(text)
    if m:
        out['kid_type'] = m.group(1).lower()
    # notes: capture subject lines or lines with 'note' or remaining text
    notes = []
    for line in text.splitlines():
        if re.search(r"note|notes|comment|comments|suggested", line, re.IGNORECASE):
            notes.append(line.strip())
    if not notes:
        # take first non-empty short line
        for line in text.splitlines():
            s = line.strip()
            if s and len(s) < 120:
                notes.append(s)
                break
    out['notes'] = ' | '.join(notes)
    return out


def next_id(csv_path: str) -> int:
    if not os.path.exists(csv_path):
        return 1
    with open(csv_path, newline='') as f:
        reader = csv.DictReader(f)
        ids = [int(r['id']) for r in reader if r.get('id')]
        return max(ids) + 1 if ids else 1


def append_row(parsed: dict, csv_path: str = OUT_CSV):
    idn = next_id(csv_path)
    latlon = geocode_address(parsed['address'])
    lat = lon = ''
    if latlon:
        lat, lon = latlon
    row = {
        'id': idn,
        'address': parsed['address'],
        'miles': parsed['miles'],
        'time_minutes': parsed['time_minutes'],
        'kid_type': parsed['kid_type'],
        'notes': parsed['notes'],
        'lat': lat,
        'lon': lon,
        'demand': '',
        'service_time': '',
        'tw_start': '',
        'tw_end': ''
    }
    write_header = not os.path.exists(csv_path)
    with open(csv_path, 'a', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=HEADERS)
        if write_header:
            writer.writeheader()
        writer.writerow(row)
    print('Appended route id', idn, 'to', csv_path)


if __name__ == '__main__':
    if len(sys.argv) > 1:
        path = sys.argv[1]
        with open(path, encoding='utf-8') as f:
            text = f.read()
    else:
        text = sys.stdin.read()
    parsed = parse_text(text)
    append_row(parsed)
