"""Import route_vehicle_*.csv files directly into the sqlite DB (data.db).

This writes into tables `drivers` and `trips` using the same JSON payload shape expected by the app.
"""
import os
import glob
import csv
import json
import sqlite3
from contextlib import closing

DB_PATH = os.environ.get('ROUTES_DB_PATH', 'data.db')


def read_route_csv(path):
    rows = []
    with open(path, newline='', encoding='utf-8') as fh:
        rdr = csv.DictReader(fh)
        for r in rdr:
            rows.append(r)
    return rows


def import_all():
    files = sorted(glob.glob('route_vehicle_*.csv'))
    if not files:
        print('No route CSV files found')
        return
    drivers = []
    trips = []
    for f in files:
        name = os.path.basename(f)
        parts = name.replace('.csv','').split('_')
        vid = parts[-1]
        rows = read_route_csv(f)
        # create driver payload using first non-zero lat/lon or 0,0
        driver_lat = 0.0
        driver_lon = 0.0
        for r in rows:
            try:
                lat = float(r.get('lat') or 0)
                lon = float(r.get('lon') or 0)
            except Exception:
                lat = 0.0
                lon = 0.0
            if driver_lat == 0.0 and lat != 0.0:
                driver_lat = lat
            if driver_lon == 0.0 and lon != 0.0:
                driver_lon = lon
        driver = {'id': str(vid), 'lat': driver_lat, 'lon': driver_lon, 'active': True}
        drivers.append(driver)
        for i, r in enumerate(rows):
            tid = f"{vid}_stop_{i+1}"
            try:
                lat = float(r.get('lat') or 0)
                lon = float(r.get('lon') or 0)
            except Exception:
                lat = 0.0
                lon = 0.0
            stop_label = r.get('stop') or tid
            trip = {'id': tid, 'lat': lat, 'lon': lon, 'stop': stop_label}
            # copy any useful columns
            for k in ('service_sec','eta_sec','depart_sec','eta_hhmm','depart_hhmm'):
                if k in r and r[k] != '':
                    try:
                        trip[k] = int(float(r[k])) if 'sec' in k else r[k]
                    except Exception:
                        trip[k] = r[k]
            trips.append(trip)

    print(f'Found {len(drivers)} drivers and {len(trips)} trips; writing to DB {DB_PATH}')
    # write to sqlite
    with closing(sqlite3.connect(DB_PATH)) as conn:
        cur = conn.cursor()
        written_d = 0
        written_t = 0
        for d in drivers:
            try:
                cur.execute('REPLACE INTO drivers (id, payload) VALUES (?, ?)', (str(d.get('id')), json.dumps(d)))
                written_d += 1
            except Exception as e:
                print('driver write error', d.get('id'), e)
        for t in trips:
            try:
                cur.execute('REPLACE INTO trips (id, payload) VALUES (?, ?)', (str(t.get('id')), json.dumps(t)))
                written_t += 1
            except Exception as e:
                print('trip write error', t.get('id'), e)
        conn.commit()
    print('Wrote drivers:', written_d, 'trips:', written_t)

if __name__ == '__main__':
    import_all()
