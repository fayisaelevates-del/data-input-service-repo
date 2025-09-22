"""Robust converter for coordinate/address rows -> converted_trips.json

Features:
- Accepts CSV/TSV with headers (auto-sniffs delimiter). If headers include 'lat' and 'lon'
  those columns are used directly. If 'address' or 'label' exists it is preserved.
- If no CSV headers detected, falls back to regex extraction of lat/lon pairs per line.
- Attempts multiple encodings (utf-8, utf-8-sig, latin-1) to avoid decode errors.
- Deduplicates coordinates (by rounded lat/lon) and preserves simple labels.
- Optional Nominatim geocode (off by default) for rows that include addresses but not lat/lon.

Usage:
  python convert_coords_to_trips.py input.tsv [--out converted_trips.json] [--geocode nominatum|none]

Output:
  JSON file with shape {"drivers": [...], "trips": [...]}
"""

import sys
import re
import json
import csv
import time
from pathlib import Path
from typing import List, Dict, Optional


def guess_encoding(path: Path) -> Optional[str]:
    # try utf-8, utf-8-sig, latin-1
    for enc in ('utf-8', 'utf-8-sig', 'latin-1'):
        try:
            with path.open('r', encoding=enc) as fh:
                fh.readline()
            return enc
        except Exception:
            continue
    return None


def extract_latlon_from_text(text: str) -> List[Dict]:
    latlon_re = re.compile(r'(-?\d+\.\d+)\s*,?\s*(-?\d+\.\d+)')
    out = []
    for m in latlon_re.finditer(text):
        try:
            lat = float(m.group(1))
            lon = float(m.group(2))
        except Exception:
            continue
        # label heuristics: take left context (up to 120 chars) or right if left lacks letters
        start = max(0, m.start() - 120)
        left = text[start:m.start()].strip(' ,;\t')
        right = text[m.end():m.end() + 120].strip(' ,;\t')
        label = ''
        if re.search(r'[A-Za-z]', left):
            label = left
        elif re.search(r'[A-Za-z]', right):
            label = right
        label = re.sub(r'\s+', ' ', label).strip()
        out.append({'lat': lat, 'lon': lon, 'label': label})
    return out


def clean_label(raw: str) -> str:
    """Clean noisy label text: remove embedded lat/lon pairs, strip surrounding punctuation,
    collapse whitespace, and truncate to a reasonable length. Prefer substrings that look like
    an address (contain street words or commas).
    """
    if not raw:
        return ''
    s = raw
    # remove embedded coordinate pairs like '32.2753731 -110.9443301' or '32.27, -110.94'
    s = re.sub(r"-?\d+\.\d+\s*,?\s*-?\d+\.\d+", ' ', s)
    # remove stray numbers that look like indexes (leading '1.' or '4 ') but keep house numbers
    s = re.sub(r'^[0-9]{1,3}\s+[-.:]?\s*', '', s)
    # collapse whitespace and separators
    s = re.sub(r'[\t\n\r]+', ' ', s)
    s = re.sub(r'\s{2,}', ' ', s)
    s = s.strip(' -:;,.')
    # if the label is long, try to find a reasonable address-like fragment
    if len(s) > 120:
        # prefer substring containing common street keywords or a comma
        m = re.search(r'([A-Za-z0-9\s,.#-]{10,120}(Street|St|Avenue|Ave|Road|Rd|Drive|Dr|Blvd|Boulevard|Way|Ct|Court|Place|Ln|Loop|Ter|Trail|Parkway|Pkwy|,))', s, re.IGNORECASE)
        if m:
            s = m.group(0).strip()
        else:
            s = s[:120].rsplit(' ', 1)[0]
    return s


def nominatim_geocode(address: str, email: Optional[str] = None) -> Optional[Dict]:
    # lightweight Nominatim lookup with a polite 1s delay; requires requests
    try:
        import requests
    except Exception:
        return None
    params = {'q': address, 'format': 'json', 'limit': 1}
    if email:
        params['email'] = email
    try:
        resp = requests.get('https://nominatim.openstreetmap.org/search', params=params, headers={'User-Agent': 'convert_coords/1.0'})
        time.sleep(1.0)  # polite delay
        if resp.status_code == 200:
            arr = resp.json()
            if arr:
                return {'lat': float(arr[0]['lat']), 'lon': float(arr[0]['lon']), 'display_name': arr[0].get('display_name')}
    except Exception:
        return None
    return None


def main(argv: List[str]):
    if len(argv) < 2:
        print('Usage: python convert_coords_to_trips.py <input-file> [--out out.json] [--geocode nominatim]')
        return 2

    inpath = Path(argv[1])
    if not inpath.exists():
        print('Input path not found:', inpath)
        return 2

    outpath = Path('converted_trips.json')
    geocode = None
    if '--out' in argv:
        try:
            outpath = Path(argv[argv.index('--out') + 1])
        except Exception:
            pass
    if '--geocode' in argv:
        try:
            geocode = argv[argv.index('--geocode') + 1]
        except Exception:
            geocode = None

    enc = guess_encoding(inpath) or 'utf-8'
    # try CSV sniffing
    trips = []
    seen = set()
    tid = 1

    with inpath.open('r', encoding=enc, errors='replace') as fh:
        full_text = fh.read()
        # strip common code fences (```) that may appear when copying from chat
        full_text = full_text.replace('```', '')
        # sample for csv sniffing
        sample = full_text[:8192]
        # prepare a file-like iterator over sanitized text
        fh_lines = full_text.splitlines()
        # use an in-memory iterator where needed
        fh_iter = iter(fh_lines)
        # helper to get content when needed
        def fh_read(n=0):
            return full_text
        delim = None
        try:
            sn = csv.Sniffer()
            dialect = sn.sniff(sample)
            delim = dialect.delimiter
        except Exception:
            # fallback: if tabs present prefer tabs
            if '\t' in sample:
                delim = '\t'
            elif ',' in sample:
                delim = ','
            else:
                delim = None

        if delim:
            # peek first line to detect header presence
            first_line = sample.splitlines()[0] if sample.splitlines() else ''
            headers_candidates = [h.strip() for h in first_line.split(delim)]
            has_latlon_header = any(h.lower() in ('lat', 'latitude') for h in headers_candidates) and any(h.lower() in ('lon', 'lng', 'longitude') for h in headers_candidates)
            if has_latlon_header:
                reader = csv.DictReader(fh, delimiter=delim)
                row_idx = 0
                for row in reader:
                    row_idx += 1
                    lat_key = next((k for k in row.keys() if k and k.lower() in ('lat', 'latitude')), None)
                    lon_key = next((k for k in row.keys() if k and k.lower() in ('lon', 'lng', 'longitude')), None)
                    label_key = next((k for k in row.keys() if k and k.lower() in ('address', 'label', 'stop')), None)
                    if lat_key and lon_key and row.get(lat_key) and row.get(lon_key):
                        try:
                            lat = float(row[lat_key])
                            lon = float(row[lon_key])
                        except Exception:
                            continue
                        key = (round(lat, 6), round(lon, 6))
                        if key in seen:
                            continue
                        seen.add(key)
                        label = (row.get(label_key) or '').strip() if label_key else ''
                        trips.append({'id': f'trip-{tid}', 'lat': lat, 'lon': lon, 'label': label, 'demand': int(row.get('demand') or 1), 'service_sec': int(row.get('service_time') or row.get('service_sec') or 600), 'tw_start': int(row.get('tw_start') or row.get('tw_start_sec') or 5*3600), 'tw_end': int(row.get('tw_end') or row.get('tw_end_sec') or 17*3600), 'source_row': row_idx})
                        tid += 1
                        continue
                    # fallback: geocode address if requested
                    if label_key and geocode and (row.get(label_key) or '').strip():
                        addr = (row.get(label_key) or '').strip()
                        if geocode and geocode.lower().startswith('nominatim'):
                            res = nominatim_geocode(addr)
                            if res:
                                lat = res['lat']
                                lon = res['lon']
                                key = (round(lat,6), round(lon,6))
                                if key in seen:
                                    continue
                                seen.add(key)
                                trips.append({'id': f'trip-{tid}', 'lat': lat, 'lon': lon, 'label': addr, 'demand': int(row.get('demand') or 1), 'service_sec': int(row.get('service_time') or 600), 'tw_start': int(row.get('tw_start') or 5*3600), 'tw_end': int(row.get('tw_end') or 17*3600), 'source_row': row_idx})
                                tid += 1
                                continue
                # done reading CSV with headers
            else:
                # treat as headerless: fall back to freeform line parsing
                # headerless: iterate sanitized lines
                row_idx = 0
                for raw in fh_iter:
                    row_idx += 1
                    raw = raw.strip()
                    if not raw:
                        continue
                    extracted = extract_latlon_from_text(raw)
                    if extracted:
                        for ex in extracted:
                            key = (round(ex['lat'], 6), round(ex['lon'], 6))
                            if key in seen:
                                continue
                            seen.add(key)
                            label = clean_label(ex.get('label') or '')
                            trips.append({'id': f'trip-{tid}', 'lat': ex['lat'], 'lon': ex['lon'], 'label': label, 'demand': 1, 'service_sec': 600, 'tw_start': 5*3600, 'tw_end': 17*3600, 'source_row': row_idx})
                            tid += 1
                    else:
                        if geocode and geocode.lower().startswith('nominatim'):
                            addr = raw
                            res = nominatim_geocode(addr)
                            if res:
                                key = (round(res['lat'],6), round(res['lon'],6))
                                if key in seen:
                                    continue
                                seen.add(key)
                                trips.append({'id': f'trip-{tid}', 'lat': res['lat'], 'lon': res['lon'], 'label': addr, 'demand': 1, 'service_sec': 600, 'tw_start': 5*3600, 'tw_end': 17*3600, 'source_row': row_idx})
                                tid += 1
        else:
            # treat as freeform lines with lat/lon pairs
            fh.seek(0)
            row_idx = 0
            for raw in fh:
                row_idx += 1
                raw = raw.strip()
                if not raw:
                    continue
                extracted = extract_latlon_from_text(raw)
                if extracted:
                    for ex in extracted:
                        key = (round(ex['lat'], 6), round(ex['lon'], 6))
                        if key in seen:
                            continue
                        seen.add(key)
                        label = clean_label(ex.get('label') or '')
                        trips.append({'id': f'trip-{tid}', 'lat': ex['lat'], 'lon': ex['lon'], 'label': label, 'demand': 1, 'service_sec': 600, 'tw_start': 5*3600, 'tw_end': 17*3600, 'source_row': row_idx})
                        tid += 1
                    else:
                        # no coordinate found; optionally geocode if requested
                        if geocode and geocode.lower().startswith('nominatim'):
                            addr = raw
                            res = nominatim_geocode(addr)
                            if res:
                                key = (round(res['lat'],6), round(res['lon'],6))
                                if key in seen:
                                    continue
                                seen.add(key)
                                trips.append({'id': f'trip-{tid}', 'lat': res['lat'], 'lon': res['lon'], 'label': addr, 'demand': 1, 'service_sec': 600, 'tw_start': 5*3600, 'tw_end': 17*3600, 'source_row': row_idx})
                                tid += 1
                # if headerless parsing yielded nothing, fall back to scanning whole text for lat/lon
        # end with delim handling
    if not trips:
        # attempt full-text extraction as a last resort
        full_matches = extract_latlon_from_text(full_text)
        row_idx = 0
        for ex in full_matches:
            row_idx += 1
            key = (round(ex['lat'], 6), round(ex['lon'], 6))
            if key in seen:
                continue
            seen.add(key)
            label = clean_label(ex.get('label') or '')
            trips.append({'id': f'trip-{tid}', 'lat': ex['lat'], 'lon': ex['lon'], 'label': label, 'demand': 1, 'service_sec': 600, 'tw_start': 5*3600, 'tw_end': 17*3600, 'source_row': row_idx})
            tid += 1
    # drivers: use first coordinate as depot/driver unless a drivers-like column exists (not implemented yet)
    drivers = []
    if trips:
        dep = trips[0]
        drivers.append({'id': 'drv-1', 'lat': dep['lat'], 'lon': dep['lon'], 'label': 'Depot / Vehicle 1', 'active': True})

    payload = {'drivers': drivers, 'trips': trips}
    try:
        with outpath.open('w', encoding='utf-8') as fh:
            json.dump(payload, fh, indent=2)
        print(f'Wrote {outpath} drivers={len(drivers)} trips={len(trips)}')
    except Exception as e:
        print('Write failed:', e)


if __name__ == '__main__':
    raise SystemExit(main(sys.argv))