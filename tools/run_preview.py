import importlib
import sys
import time
import json
# ruff: noqa: E402
sys.path.append(r"c:\Users\safer\OneDrive\Documents\Route Management Code\mycloudrunproject")
import serve_routes
importlib.reload(serve_routes)
print('Running build_preview()...')
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
count=0
for k,v in per.items():
    print(k, ':', len(v), 'trips')
    count += 1
    if count >= 12:
        break
print('\nPreview route sample stats (first 8):')
prs = preview.get('preview_routes', {})
count=0
for k in list(prs.keys())[:8]:
    r = prs[k]
    print(k, 'route_len=', len(r.get('route',[])), 'stops=', len(r.get('stops',[])))
    count += 1

# write small preview file for inspection
with open('preview_summary.json','w') as fh:
    json.dump({'assigned_drivers': assigned_drivers, 'assigned_trips': assigned_trips, 'remaining_trips': len(remaining), 'per_driver_sample': dict(list(per.items())[:20])}, fh)
print('\nWrote preview_summary.json')
