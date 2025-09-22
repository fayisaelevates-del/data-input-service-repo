"""
Small utility to load stops/demands/time-windows from a CSV exported from Google Sheets.
Expected CSV columns: id,lat,lon,demand,tw_start,tw_end
Writes `input.json` with the standardized structure used by vrp_prototype.
"""
import csv
import json

def csv_to_input(csv_path: str, out_path: str = 'input.json'):
    rows = []
    with open(csv_path, newline='') as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append(r)
    # sort so depot (id=0) is first if present
    rows_sorted = sorted(rows, key=lambda r: int(r.get('id', 0)))
    stops = []
    demands = []
    tws = []
    for r in rows_sorted:
        stops.append((float(r['lat']), float(r['lon'])))
        demands.append(int(r.get('demand', 0)))
        tws.append((int(r.get('tw_start', 0)), int(r.get('tw_end', 28800))))
    payload = {'stops': stops, 'demands': demands, 'time_windows': tws}
    with open(out_path, 'w') as f:
        json.dump(payload, f, indent=2)
    print('Wrote', out_path)


if __name__ == '__main__':
    import sys
    if len(sys.argv) < 2:
        print('Usage: python sheets_input.py stops.csv [out.json]')
    else:
        csv_to_input(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else 'input.json')
