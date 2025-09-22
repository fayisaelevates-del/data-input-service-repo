"""
Watch `inbox/` for route files and import them into the app DB so previews can be built automatically.
- Accepts JSON files with shape: {"drivers": [...], "trips": [...]} and CSV files matching route_vehicle_*.csv rows (sequence,stop,lat,lon,...)
- Moves processed files into `inbox/processed/`
- After import, calls `serve_routes.build_preview()` and writes `preview.json` (fast path for UI)

Usage:
  python tools/import_watch.py

"""
import time
import os
import json
import csv
from pathlib import Path
# ruff: noqa: E402
ROOT = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(ROOT))
import serve_routes

INBOX = Path(ROOT) / 'inbox'
PROCESSED = INBOX / 'processed'
INBOX.mkdir(parents=True, exist_ok=True)
PROCESSED.mkdir(parents=True, exist_ok=True)

POLL = float(os.environ.get('IMPORT_WATCH_POLL', '3'))

print(f'Watching {INBOX} every {POLL}s for route files...')


def import_json(path: Path):
    try:
        with open(path) as f:
            data = json.load(f)
        drivers = data.get('drivers', [])
        trips = data.get('trips', [])
        for d in drivers:
            serve_routes.upsert_driver(d)
        for t in trips:
            serve_routes.upsert_trip(t)
        print(f'Imported JSON {path.name}: drivers={len(drivers)} trips={len(trips)}')
        return True
    except Exception as e:
        print('Failed to import JSON', path, e)
        return False


def import_csv(path: Path):
    # Expect CSV from route_vehicle_n.csv with header including lat, lon, stop
    imported = 0
    try:
        with open(path, newline='') as cf:
            reader = csv.DictReader(cf)
            for i, row in enumerate(reader, start=1):
                lat = row.get('lat') or row.get('latitude') or row.get('Lat')
                lon = row.get('lon') or row.get('longitude') or row.get('Lon')
                if not lat or not lon:
                    continue
                tid = row.get('trip_id') or row.get('stop') or f'{path.stem}-{i}'
                t = {'id': str(tid), 'lat': float(lat), 'lon': float(lon), 'label': row.get('label') or tid}
                serve_routes.upsert_trip(t)
                imported += 1
        print(f'Imported CSV {path.name}: trips={imported}')
        return True
    except Exception as e:
        print('Failed to import CSV', path, e)
        return False


def process_file(path: Path):
    lower = path.suffix.lower()
    ok = False
    if lower == '.json':
        ok = import_json(path)
    elif lower in ('.csv', '.txt'):
        ok = import_csv(path)
    else:
        print('Skipping unknown file type', path.name)
    # move file to processed or failed
    dest = PROCESSED / path.name
    # ensure unique name
    if dest.exists():
        dest = PROCESSED / (path.stem + '_' + str(int(time.time())) + path.suffix)
    try:
        path.replace(dest)
    except Exception:
        try:
            path.unlink()
        except Exception:
            pass
    return ok


def write_preview_file(payload):
    out = Path(ROOT) / 'preview.json'
    try:
        with open(out, 'w') as f:
            json.dump(payload, f, indent=2)
        print('Wrote preview.json')
    except Exception as e:
        print('Failed to write preview.json', e)


if __name__ == '__main__':
    try:
        while True:
            for p in INBOX.iterdir():
                if p.is_file() and not p.name.startswith('.'):
                    print('Found file', p.name)
                    success = process_file(p)
                    if success:
                        # build preview and write preview.json (not overwriting preview_sample.json)
                        try:
                            payload = serve_routes.build_preview()
                            write_preview_file(payload)
                        except Exception as e:
                            print('build_preview failed:', e)
            time.sleep(POLL)
    except KeyboardInterrupt:
        print('Stopping import watcher')
