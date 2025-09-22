"""Annotate existing route_vehicle_*.csv files with human-readable ETA/depart HH:MM columns.
Uses SHIFT_START if available from vrp_prototype, otherwise assumes 0.
"""
import csv
import glob
import os

# try to import SHIFT_START from vrp_prototype to keep consistency
SHIFT_START = 0
try:
    from vrp_prototype import SHIFT_START
except Exception:
    try:
        import json
        # attempt to read input.json shift override
        if os.path.exists('input.json'):
            with open('input.json') as f:
                data = json.load(f)
            if 'shift_start_seconds' in data:
                SHIFT_START = int(data['shift_start_seconds'])
    except Exception:
        SHIFT_START = 0


def seconds_to_hhmm(sec: int) -> str:
    try:
        abs_sec = int(sec) + int(SHIFT_START)
        abs_sec = abs_sec % (24 * 3600)
        hh = abs_sec // 3600
        mm = (abs_sec % 3600) // 60
        return f"{hh:02d}:{mm:02d}"
    except Exception:
        return ''

pattern = os.path.join(os.getcwd(), 'route_vehicle_*.csv')
files = sorted(glob.glob(pattern))
updated = 0
for f in files:
    try:
        with open(f, 'r', newline='') as rf:
            reader = list(csv.DictReader(rf))
            if not reader:
                continue
            # if eta_hhmm or depart_hhmm already present, skip
            if 'eta_hhmm' in reader[0] or 'depart_hhmm' in reader[0]:
                continue
            # add columns
            for row in reader:
                eta = int(float(row.get('eta_sec') or 0))
                depart = int(float(row.get('depart_sec') or row.get('eta_sec') or 0))
                row['eta_hhmm'] = seconds_to_hhmm(eta)
                row['depart_hhmm'] = seconds_to_hhmm(depart)
                # ensure violates_shift exists
                if 'violates_shift' not in row:
                    row['violates_shift'] = ''
        # write back with new header
        fieldnames = list(reader[0].keys())
        tmp = f + '.tmp'
        with open(tmp, 'w', newline='') as wf:
            writer = csv.DictWriter(wf, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(reader)
        os.replace(tmp, f)
        updated += 1
    except Exception as e:
        print(f'Failed annotating {f}: {e}')

print(f'Annotated {updated} files (added eta_hhmm/depart_hhmm)')