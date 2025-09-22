"""Regenerate routes_summary.csv from existing route_vehicle_*.csv files.
This script scans for route CSVs, reads the last depart_sec (route duration), and writes routes_summary.csv.
"""
import csv
import glob
import os

pattern = os.path.join(os.getcwd(), 'route_vehicle_*.csv')
files = sorted(glob.glob(pattern))
rows = []
for f in files:
    base = os.path.basename(f)
    try:
        vehicle = int(base.replace('route_vehicle_', '').replace('.csv', ''))
    except Exception:
        continue
    total_seconds = 0
    violates = False
    try:
        with open(f, 'r', newline='') as cf:
            reader = csv.DictReader(cf)
            last = None
            for r in reader:
                last = r
            if last:
                # prefer depart_sec if present, else eta_sec
                if 'depart_sec' in last and last['depart_sec']:
                    total_seconds = int(float(last['depart_sec']))
                elif 'eta_sec' in last and last['eta_sec']:
                    total_seconds = int(float(last['eta_sec']))
                if 'violates_shift' in last:
                    v = last['violates_shift'].strip().lower()
                    violates = v in ('1', 'true', 'yes')
    except Exception as e:
        print(f'Failed reading {f}: {e}')
    rows.append({'vehicle': vehicle, 'total_seconds': total_seconds, 'total_hours': round(total_seconds/3600.0, 2), 'violates_shift': violates})

# sort by vehicle
rows = sorted(rows, key=lambda x: x['vehicle'])

outname = os.path.join(os.getcwd(), 'routes_summary.csv')
with open(outname, 'w', newline='') as of:
    fieldnames = ['vehicle', 'total_seconds', 'total_hours', 'violates_shift']
    w = csv.DictWriter(of, fieldnames=fieldnames)
    w.writeheader()
    for r in rows:
        w.writerow(r)

print(f'Wrote {outname} ({len(rows)} rows)')
for r in rows[:10]:
    print(r)