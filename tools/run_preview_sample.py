"""Run a fast preview using a small sample of drivers/trips from the DB to produce a quick summary.
"""
# ruff: noqa: E402
import sqlite3
import json
import time
import os
import importlib
import sys
sys.path.append(r"c:\Users\safer\OneDrive\Documents\Route Management Code\mycloudrunproject")
import serve_routes
importlib.reload(serve_routes)

DB = os.environ.get('ROUTES_DB_PATH', 'data.db')

def load_sample(drivers_n=8, trips_n=40):
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute('SELECT payload FROM drivers LIMIT ?', (drivers_n,))
    drivers = [json.loads(r[0]) for r in cur.fetchall()]
    cur.execute('SELECT payload FROM trips LIMIT ?', (trips_n,))
    trips = [json.loads(r[0]) for r in cur.fetchall()]
    conn.close()
    return drivers, trips

drivers, trips = load_sample()
print(f'Loaded sample drivers={len(drivers)} trips={len(trips)}')
# monkeypatch the module functions used by build_preview
serve_routes.get_all_drivers = lambda: {str(d.get('id')): d for d in drivers}
serve_routes.get_all_trips = lambda: list(trips)
# reduce eval top n to 1 for speed
os.environ['ASSIGN_EVAL_TOP_N'] = '1'

print('Calling build_preview() with sample...')
start = time.time()
preview = serve_routes.build_preview()
print('Elapsed:', time.time() - start)
per = preview.get('per_driver_trip_ids', {})
assigned_drivers = len([k for k,v in per.items() if v])
assigned_trips = sum(len(v) for v in per.values())
remaining = preview.get('remaining', [])
print('assigned_drivers=', assigned_drivers)
print('assigned_trips=', assigned_trips)
print('remaining_trips=', len(remaining))
print('\nSample per-driver assignment (up to 12):')
for i, (k, v) in enumerate(per.items()):
    print(k, ':', len(v), 'trips')
    if i >= 11:
        break

# write summary file
with open('preview_sample_summary.json','w') as fh:
    json.dump({'assigned_drivers': assigned_drivers, 'assigned_trips': assigned_trips, 'remaining_trips': len(remaining), 'per_driver_sample': dict(list(per.items())[:20])}, fh)
print('\nWrote preview_sample_summary.json')
