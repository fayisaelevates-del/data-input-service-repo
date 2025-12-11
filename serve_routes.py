from flask import Flask, send_from_directory, jsonify, render_template_string, abort
from flask import request as flask_request
import os
import json
import re
from functools import wraps
from typing import List, Dict, Any
try:
    import vrp_prototype
except Exception as _e:
    # Fallback shim so the Flask app can start even if vrp_prototype or its heavy
    # dependencies (OR-Tools, openrouteservice) are not available in the environment.
    # The shim provides the minimal symbols the rest of this module expects.
    class _Shim:
        STOPS = [(32.257254, -110.9723225)]
        SERVICE_TIMES = [0]
        SHIFT_SECONDS = 24 * 3600

        @staticmethod
        def haversine(a, b):
            import math
            lat1, lon1 = a
            lat2, lon2 = b
            R = 6371
            phi1 = math.radians(lat1)
            phi2 = math.radians(lat2)
            dphi = math.radians(lat2 - lat1)
            dlambda = math.radians(lon2 - lon1)
            x = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
            return 2 * R * math.asin(math.sqrt(x))

        @staticmethod
        def build_time_matrix(stops):
            # return symmetric matrix of integer seconds using haversine approx at 50 km/h
            n = len(stops)
            tm = [[0] * n for _ in range(n)]
            for i in range(n):
                for j in range(n):
                    if i == j:
                        tm[i][j] = 0
                    else:
                        km = _Shim.haversine(stops[i], stops[j])
                        tm[i][j] = int(km / 50.0 * 3600)
            return tm

        @staticmethod
        def solve_vrp(time_matrix, num_vehicles, depot, demands=None, vehicle_capacities=None, service_times=None, time_windows=None):
            # Very small deterministic fallback: for each vehicle return a trivial route that visits stops in order
            n = len(time_matrix)
            if n <= 1:
                return [[0, 0] for _ in range(num_vehicles)]
            # single-vehicle fallback: visit nodes 0..n-1 then back to 0
            seq = list(range(n)) + [0]
            return [seq] * max(1, num_vehicles)

        @staticmethod
        def save_outputs(routes, stops, tm):
            # Minimal writer: write a simple routes.json listing vehicles and stops
            out = []
            for i, r in enumerate(routes, start=1):
                total_sec = 0
                # estimate total seconds by summing travel along r
                for a, b in zip(r, r[1:]):
                    try:
                        total_sec += int(tm[a][b])
                    except Exception:
                        pass
                out.append({'vehicle': i, 'stops': [], 'total_seconds': total_sec, 'total_hours': round(total_sec/3600.0, 2)})
            try:
                with open('routes.json', 'w', encoding='utf-8') as fh:
                    json.dump(out, fh, indent=2)
            except Exception:
                pass

    vrp_prototype = _Shim()

# For typing consumers, declare the module as Any when the real module isn't available
try:
    # If vrp_prototype is a module object, mypy may treat it differently; hint as Any
    vrp_prototype  # type: Any
except Exception:
    pass
import sqlite3
import time
import urllib.parse
import urllib.request
from contextlib import closing

# SQLite data file
DB_PATH = os.environ.get('ROUTES_DB_PATH', 'data.db')


def init_db():
    with closing(sqlite3.connect(DB_PATH)) as conn:
        cur = conn.cursor()
        cur.execute('''
        CREATE TABLE IF NOT EXISTS drivers (
            id TEXT PRIMARY KEY,
            payload TEXT NOT NULL
        )
        ''')
        cur.execute('''
        CREATE TABLE IF NOT EXISTS trips (
            id TEXT PRIMARY KEY,
            payload TEXT NOT NULL
        )
        ''')
        # history/audit tables
        cur.execute('''
        CREATE TABLE IF NOT EXISTS history_trips (
            id TEXT PRIMARY KEY,
            payload TEXT NOT NULL,
            archived_at REAL NOT NULL
        )
        ''')
        cur.execute('''
        CREATE TABLE IF NOT EXISTS preview_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            applied_ids TEXT NOT NULL,
            preview_payload TEXT NOT NULL,
            applied_at REAL NOT NULL
        )
        ''')
        # cache for geocoding results: key is normalized query, value is JSON payload with lat/lon
        cur.execute('''
        CREATE TABLE IF NOT EXISTS geocode_cache (
            query TEXT PRIMARY KEY,
            lat REAL,
            lon REAL,
            fetched_at REAL
        )
        ''')
        # preferences for CSV mapping: id can be a user/token/session key
        cur.execute('''
        CREATE TABLE IF NOT EXISTS mapping_prefs (
            id TEXT PRIMARY KEY,
            payload TEXT NOT NULL,
            updated_at REAL NOT NULL
        )
        ''')
        conn.commit()


def upsert_driver(d: Dict):
    with closing(sqlite3.connect(DB_PATH)) as conn:
        cur = conn.cursor()
        cur.execute('REPLACE INTO drivers (id, payload) VALUES (?, ?)', (str(d.get('id')), json.dumps(d)))
        conn.commit()


def upsert_trip(t: Dict):
    with closing(sqlite3.connect(DB_PATH)) as conn:
        cur = conn.cursor()
        cur.execute('REPLACE INTO trips (id, payload) VALUES (?, ?)', (str(t.get('id')), json.dumps(t)))
        conn.commit()


def upsert_mapping_pref(p: Dict):
    """Persist a mapping preference dict with keys: id, payload (mapping dict), updated_at"""
    with closing(sqlite3.connect(DB_PATH)) as conn:
        cur = conn.cursor()
        cur.execute('REPLACE INTO mapping_prefs (id, payload, updated_at) VALUES (?, ?, ?)', (str(p.get('id')), json.dumps(p.get('payload') or p.get('mapping') or {}), float(p.get('updated_at') or time.time())))
        conn.commit()


def get_mapping_pref(pid: str):
    with closing(sqlite3.connect(DB_PATH)) as conn:
        cur = conn.cursor()
        cur.execute('SELECT payload FROM mapping_prefs WHERE id = ?', (str(pid),))
        row = cur.fetchone()
        if not row:
            return None
        try:
            return json.loads(row[0])
        except Exception:
            return None


def get_all_drivers():
    out = {}
    with closing(sqlite3.connect(DB_PATH)) as conn:
        cur = conn.cursor()
        for row in cur.execute('SELECT payload FROM drivers'):
            try:
                d = json.loads(row[0])
                out[str(d.get('id'))] = d
            except Exception:
                pass
    return out


def get_all_trips():
    out = []
    with closing(sqlite3.connect(DB_PATH)) as conn:
        cur = conn.cursor()
        for row in cur.execute('SELECT payload FROM trips'):
            try:
                t = json.loads(row[0])
                out.append(t)
            except Exception:
                pass
    return out


def get_trip_by_id(tid: str):
    with closing(sqlite3.connect(DB_PATH)) as conn:
        cur = conn.cursor()
        cur.execute('SELECT payload FROM trips WHERE id = ?', (str(tid),))
        row = cur.fetchone()
        if not row:
            return None
        try:
            return json.loads(row[0])
        except Exception:
            return None


# -- Demo helpers: geocode proxy, add trip by address, and admin page
import uuid


def _check_demo_key():
    """Check DEMO_ADMIN_KEY if set. Returns True if the request includes the key."""
    demo_key = os.environ.get('DEMO_ADMIN_KEY')
    if not demo_key:
        return False
    try:
        supplied = flask_request.headers.get('X-DEMO-KEY') or flask_request.args.get('demo_key')
        return supplied == demo_key
    except Exception:
        return False


@app.route('/api/geocode', methods=['POST'])
def api_geocode():
    """Proxy geocode endpoint for admin UI. Accepts JSON {"q": "address"} and returns {lat, lon}."""
    try:
        data = flask_request.get_json(force=True) or {}
        q = (data.get('q') or '').strip()
        if not q:
            return jsonify({'error': 'q required'}), 400
        lat, lon = _geocode_query(q)
        if lat is None or lon is None:
            return jsonify({'ok': False, 'lat': None, 'lon': None})
        return jsonify({'ok': True, 'lat': lat, 'lon': lon})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/add_trip', methods=['POST'])
def api_add_trip():
    """Add a trip by address from the admin UI. Body: {"address": "...", "label": "...", "demand": 1}
    Protected by DEMO_ADMIN_KEY when set in env.
    """
    # Demo key check (if DEMO_ADMIN_KEY is set)
    if os.environ.get('DEMO_ADMIN_KEY') and not _check_demo_key():
        return jsonify({'error': 'demo key required'}), 403
    try:
        payload = flask_request.get_json(force=True) or {}
        addr = (payload.get('address') or '').strip()
        label = payload.get('label') or ''
        demand = int(payload.get('demand') or 1)
        if not addr:
            return jsonify({'error': 'address required'}), 400
        lat, lon = _geocode_query(addr)
        if lat is None or lon is None:
            return jsonify({'error': 'geocode failed for address'}), 400
        tid = f"demo-{uuid.uuid4().hex[:8]}"
        trip = {'id': tid, 'lat': float(lat), 'lon': float(lon), 'label': label, 'demand': demand, 'service_sec': 600, 'tw_start': 5*3600, 'tw_end': 17*3600}
        upsert_trip(trip)
        return jsonify({'ok': True, 'trip': trip})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/trips_for_admin', methods=['GET'])
def api_trips_for_admin():
    """Return all trips for admin UI. If DEMO_ADMIN_KEY is set, require it."""
    if os.environ.get('DEMO_ADMIN_KEY') and not _check_demo_key():
        return jsonify({'error': 'demo key required'}), 403
    try:
        trips = get_all_trips()
        return jsonify({'ok': True, 'trips': trips})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/demo/build_preview', methods=['POST'])
def demo_build_preview():
    """Build a preview using existing build_preview() and return result. Protected by demo key if set."""
    if os.environ.get('DEMO_ADMIN_KEY') and not _check_demo_key():
        return jsonify({'error': 'demo key required'}), 403
    try:
        res = build_preview()
        return jsonify({'ok': True, 'result': res})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/demo/simulate_breakdown', methods=['POST'])
def demo_simulate_breakdown():
    """Simulate a driver breakdown for demo purposes.
    Optional JSON body: {'driver_id': '<id>'}. If not provided, a random active driver is chosen.
    This endpoint computes the current preview, temporarily marks the chosen driver inactive,
    recomputes the preview, then restores the driver record. It returns the before/after
    previews and a compact list of trip reassignments suggested by the system.
    Protected by DEMO_ADMIN_KEY when set.
    """
    # Demo key check (if DEMO_ADMIN_KEY is set)
    if os.environ.get('DEMO_ADMIN_KEY') and not _check_demo_key():
        return jsonify({'error': 'demo key required'}), 403
    try:
        payload = flask_request.get_json(force=True) or {}
        chosen = payload.get('driver_id')

        drivers = get_all_drivers()
        active_drvs = [d for d in drivers.values() if d.get('active', True)]
        if not active_drvs:
            return jsonify({'error': 'no active drivers available to simulate'}), 400

        # choose a driver if not supplied
        if not chosen:
            import random
            chosen_drv = random.choice(active_drvs)
        else:
            chosen_drv = drivers.get(str(chosen))
            if not chosen_drv:
                return jsonify({'error': 'driver not found'}), 404
            if not chosen_drv.get('active', True):
                return jsonify({'error': 'driver already inactive'}), 400

        chosen_id = str(chosen_drv.get('id'))

        # baseline preview
        try:
            baseline = build_preview()
        except Exception as e:
            baseline = {'error': f'baseline build_preview failed: {e}'}

        # Temporarily mark driver inactive in DB (persisted then restored)
        original = dict(chosen_drv)
        try:
            updated = dict(chosen_drv)
            updated['active'] = False
            upsert_driver(updated)

            after = build_preview()
        except Exception as e:
            # attempt restore before returning
            try:
                upsert_driver(original)
            except Exception:
                pass
            return jsonify({'error': f'simulation failed: {e}'}), 500

        # restore driver
        try:
            upsert_driver(original)
        except Exception:
            # non-fatal; warn in response
            restore_err = True
        else:
            restore_err = False

        # compute diffs between baseline and after (based on per_driver_trip_ids)
        changes = []
        try:
            base_map = baseline.get('per_driver_trip_ids', {}) if isinstance(baseline, dict) else {}
            after_map = after.get('per_driver_trip_ids', {}) if isinstance(after, dict) else {}
            # collect all trip ids seen
            all_trip_ids = set()
            for v in base_map.values():
                all_trip_ids.update(v or [])
            for v in after_map.values():
                all_trip_ids.update(v or [])

            for tid in sorted(all_trip_ids):
                from_drv = None
                to_drv = None
                for k, v in base_map.items():
                    if v and tid in v:
                        from_drv = k
                        break
                for k, v in after_map.items():
                    if v and tid in v:
                        to_drv = k
                        break
                if from_drv != to_drv:
                    changes.append({'trip_id': tid, 'from': from_drv, 'to': to_drv})
        except Exception:
            changes = []

        resp = {'ok': True, 'simulated_driver': chosen_id, 'baseline_summary': {'per_driver_counts': {k: len(v) for k, v in (baseline.get('per_driver_trip_ids') or {}).items()}}, 'after_summary': {'per_driver_counts': {k: len(v) for k, v in (after.get('per_driver_trip_ids') or {}).items()}}, 'changes': changes, 'restore_warning': restore_err}
        return jsonify(resp)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/admin')
def admin_page():
    """Serve a small admin HTML that lets managers type addresses and add trips.
    If DEMO_ADMIN_KEY is set, the page will prompt for the key to include in requests.
    """
    try:
        return send_from_directory('.', 'admin.html')
    except Exception:
        # fallback to a tiny inline page
        html = '''<!doctype html><html><head><meta charset="utf-8"><title>Admin Demo</title></head><body><h3>Admin Demo - place holder</h3></body></html>'''
        return render_template_string(html)


def parse_csv_to_trips(fh, mapping: dict = None, geocode_missing: bool = False) -> list:
    """Parse a text file-like object into a list of trip dicts.
    Accepts CSV/TSV with header or freeform lines with lat/lon pairs.
    Optional mapping may be provided as {'lat': header_or_index, 'lon': header_or_index, 'label': header_or_index}.
    Header names (strings) or zero-based column indices (ints) are supported in mapping.
    """
    txt = fh.read()
    lines = [line.strip() for line in txt.splitlines() if line.strip()]
    if not lines:
        return []
    # detect delimiter
    sample = '\n'.join(lines[:5])
    delim = '\t' if '\t' in sample else (',' if ',' in sample else None)
    rows = []
    if delim:
        import csv as _csv
        reader = _csv.reader(lines, delimiter=delim)
        rows = list(reader)
    else:
        rows = [line.split() for line in lines]

    # header check - preserve original header strings (not lowercased) for mapping resolution
    headers = None
    if rows and any(re.search(r'lat|lon|lng|latitude|longitude|address|label|stop', h, re.I) for h in rows[0]):
        headers = rows.pop(0)

    # mapping resolution: convert header names (if provided) into column indices
    map_idx = {'lat': None, 'lon': None, 'label': None}
    if mapping and isinstance(mapping, dict):
        for k in ('lat', 'lon', 'label'):
            v = mapping.get(k)
            if isinstance(v, int):
                map_idx[k] = v
            elif isinstance(v, str) and headers:
                # try exact match then substring match (case-insensitive)
                try:
                    map_idx[k] = headers.index(v)
                except ValueError:
                    low = [h.lower() for h in headers]
                    try:
                        map_idx[k] = low.index(v.lower())
                    except ValueError:
                        for i,h in enumerate(low):
                            if v.lower() in h:
                                map_idx[k] = i
                                break

    trips = []
    tid = 1
    for r in rows:
        lat = None
        lon = None
        label = ''
        if headers:
            for i,cell in enumerate(r):
                h = headers[i] if i < len(headers) else ''
                if re.search(r'lat|latitude', h):
                    try:
                        lat = float(cell)
                    except Exception:
                        pass
                if re.search(r'lon|lng|longitude', h):
                    try:
                        lon = float(cell)
                    except Exception:
                        pass
                if re.search(r'addr|address|label|stop', h):
                    label = (label + ' ' + cell).strip()
        else:
            # try to find numeric lat/lon in cells
            for c in r:
                m = re.match(r'-?\d+\.\d+', c)
                if m:
                    if lat is None:
                        lat = float(m.group(0))
                        continue
                    if lon is None:
                        lon = float(m.group(0))
                        continue
            # if lat/lon not found, try to extract in-text
            if lat is None or lon is None:
                txtrow = ' '.join(r)
                m = re.findall(r'-?\d+\.\d+', txtrow)
                if len(m) >= 2:
                    lat = float(m[0])
                    lon = float(m[1])
                else:
                    label = txtrow

        # If lat/lon not discovered but label looks like an address and geocode_missing is True, attempt geocoding
        if (lat is None or lon is None) and geocode_missing and label:
            try:
                g_lat, g_lon = _geocode_query(label)
                if g_lat is not None and g_lon is not None:
                    lat = lat or g_lat
                    lon = lon or g_lon
            except Exception:
                pass

        if lat is not None and lon is not None:
            trips.append({'id': f'upload-{tid}', 'lat': lat, 'lon': lon, 'label': label, 'demand': 1, 'service_sec': 600, 'tw_start': 5*3600, 'tw_end': 17*3600})
            tid += 1

    return trips


def _geocode_query(query: str):
    """Lightweight Nominatim query with sqlite cache and simple rate limiting.
    Returns (lat, lon) or (None, None).
    """
    q = (query or '').strip()
    if not q:
        return (None, None)
    key = q.lower()
    # check cache
    try:
        with closing(sqlite3.connect(DB_PATH)) as conn:
            cur = conn.cursor()
            cur.execute('SELECT lat, lon, fetched_at FROM geocode_cache WHERE query = ?', (key,))
            row = cur.fetchone()
            if row and row[0] is not None and row[1] is not None:
                return (row[0], row[1])
    except Exception:
        pass

    # rate-limiting: simple per-process sleep if last call was recent
    last = getattr(_geocode_query, '_last_call', 0)
    now = time.time()
    if now - last < 1.0:
        time.sleep(1.0 - (now - last))

    # call Nominatim
    try:
        params = urllib.parse.urlencode({'q': q, 'format': 'json', 'limit': 1, 'addressdetails': 0})
        url = f'https://nominatim.openstreetmap.org/search?{params}'
        ua = os.environ.get('GEOCODER_USER_AGENT') or 'mycloudrunproject/1.0 (contact@yourdomain.example)'
        headers = {'User-Agent': ua}
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            if data and isinstance(data, list) and len(data) > 0:
                lat = float(data[0].get('lat'))
                lon = float(data[0].get('lon'))
                # store in cache
                try:
                    with closing(sqlite3.connect(DB_PATH)) as conn:
                        cur = conn.cursor()
                        cur.execute('REPLACE INTO geocode_cache (query, lat, lon, fetched_at) VALUES (?, ?, ?, ?)', (key, lat, lon, time.time()))
                        conn.commit()
                except Exception:
                    pass
                _geocode_query._last_call = time.time()
                return (lat, lon)
    except Exception:
        pass
    _geocode_query._last_call = time.time()
    return (None, None)


def archive_trips_and_record_preview(applied_ids, preview_payload):
    """Move applied trips into history_trips and record a preview_audit row."""
    import time
    ts = time.time()
    with closing(sqlite3.connect(DB_PATH)) as conn:
        cur = conn.cursor()
        for tid in applied_ids:
            # fetch current payload
            cur.execute('SELECT payload FROM trips WHERE id = ?', (str(tid),))
            row = cur.fetchone()
            if row:
                try:
                    cur.execute('REPLACE INTO history_trips (id, payload, archived_at) VALUES (?, ?, ?)', (str(tid), row[0], ts))
                except Exception:
                    pass
            try:
                cur.execute('DELETE FROM trips WHERE id = ?', (str(tid),))
            except Exception:
                pass
        # record audit
        try:
            cur.execute('INSERT INTO preview_audit (applied_ids, preview_payload, applied_at) VALUES (?, ?, ?)', (json.dumps(applied_ids), json.dumps(preview_payload), ts))
        except Exception:
            pass
        conn.commit()


# ensure DB exists on import
try:
    init_db()
except Exception:
    print('Warning: could not initialize DB at', DB_PATH)

app = Flask(__name__, static_folder='.')

# Simple in-memory storage for uploaded trips and drivers (kept for compatibility)
# DB is the primary source of truth; these caches are populated from DB on demand.
_TRIPS: List[Dict] = []
_DRIVERS: Dict[str, Dict] = {}

# Simple token auth for write endpoints

def require_token(f):
    @wraps(f)
    def inner(*args, **kwargs):
        # token may be provided via header X-API-Token; fall back to env var presence
        token = flask_request.headers.get('X-API-Token')
        env = os.environ.get('SUGGEST_API_TOKEN')
        if not token or (env and token != env):
            return jsonify({'error': 'Unauthorized'}), 401
        return f(*args, **kwargs)
    return inner

def haversine(a, b):
    # lat/lon tuples
    import math
    lat1, lon1 = a
    lat2, lon2 = b
    R = 6371
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    x = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.asin(math.sqrt(x))


@app.route('/api/trips', methods=['POST'])
@require_token
def api_trips():
    """Upload a list of trips. Each trip is {id, lat, lon, demand(optional)}."""
    try:
            payload = __import__('flask').request.get_json(force=True)
            trips = payload.get('trips') if isinstance(payload, dict) else []
            for t in trips:
                upsert_trip(t)
            # refresh in-memory cache
            global _TRIPS
            _TRIPS = get_all_trips()
            return jsonify({'ok': True, 'count': len(_TRIPS)})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@app.route('/api/drivers', methods=['POST'])
@require_token
def api_drivers():
    """Upload driver list: [{id, lat, lon, active:true|false}]"""
    try:
        payload = __import__('flask').request.get_json(force=True)
        drivers = payload.get('drivers') if isinstance(payload, dict) else []
        for d in drivers:
            upsert_driver(d)
        # refresh cache
        global _DRIVERS
        _DRIVERS = get_all_drivers()
        return jsonify({'ok': True, 'count': len(_DRIVERS)})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@app.route('/api/suggest', methods=['POST'])
@require_token
def api_suggest():
    """Return a greedy suggested assignment mapping active drivers to nearby trips.
    Strategy: for each active driver, assign the nearest unassigned trip until done.
    """
    try:
        # load from DB as source of truth
        active_drivers = [d for d in get_all_drivers().values() if d.get('active', True)]
        trips = list(get_all_trips())
        assignments = {}
        for drv in active_drivers:
            if not trips:
                break
            # find nearest trip
            best = None
            best_d = None
            drv_loc = (drv.get('lat'), drv.get('lon'))
            for t in trips:
                t_loc = (t.get('lat'), t.get('lon'))
                d = haversine(drv_loc, t_loc)
                if best is None or d < best_d:
                    best = t
                    best_d = d
            if best:
                assignments[str(drv.get('id'))] = {'trip_id': best.get('id'), 'distance_km': round(best_d, 3)}
                trips.remove(best)
        # remaining trips
        remaining = [{'id': t.get('id'), 'lat': t.get('lat'), 'lon': t.get('lon')} for t in trips]
        return jsonify({'assignments': assignments, 'remaining': remaining, 'suggested_count': len(assignments)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/upload_csv', methods=['POST'])
@require_token
def api_upload_csv():
    """Server-side CSV upload endpoint. Accepts multipart/form-data with 'file' field.
    Parses CSV/TSV or freeform text and inserts trips (and a depot driver) into the DB.
    Returns count of inserted trips.
    """
    try:
        if 'file' not in flask_request.files:
            return jsonify({'error': 'no file provided'}), 400
        f = flask_request.files['file']
        text = f.stream.read().decode('utf-8', errors='replace')
        from io import StringIO
        # optional mapping JSON in form field 'mapping'
        mapping = None
        if 'mapping' in flask_request.form:
            try:
                mapping = json.loads(flask_request.form.get('mapping'))
            except Exception:
                mapping = None
        # optional geocode flag (form field 'geocode' = '1'|'true'|'on')
        # Accept geocode via multipart form OR query string for convenience
        geocode_flag = False
        v = None
        if 'geocode' in flask_request.form:
            v = flask_request.form.get('geocode')
        elif 'geocode' in flask_request.args:
            v = flask_request.args.get('geocode')
        if v and str(v).lower() in ('1', 'true', 'on', 'yes'):
            geocode_flag = True
        trips = parse_csv_to_trips(StringIO(text), mapping=mapping, geocode_missing=geocode_flag)
        # If no trips parsed but geocoding was requested, try a robust fallback:
        # For each non-empty line, try a series of candidate queries (full line, strip parentheses,
        # text before first comma, progressively shorter token prefixes) until a geocode succeeds.
        if not trips and geocode_flag:
            fallback_trips = []
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            for ln in lines:
                # skip obvious header lines
                if ln.lower() in ('address', 'addr', 'location', 'label'):
                    continue
                candidates = []
                candidates.append(ln)
                # strip parenthetical parts: "Foo (Bar)" -> "Foo"
                candidates.append(re.sub(r"\s*\([^)]*\)", "", ln).strip())
                # take text before first comma
                if ',' in ln:
                    candidates.append(ln.split(',', 1)[0].strip())
                # progressively shorter token prefixes (first 4,3,2,1 tokens)
                toks = ln.split()
                for n in range(min(4, len(toks)), 0, -1):
                    candidates.append(' '.join(toks[:n]).strip())
                # deduplicate while preserving order
                seen = set()
                uniq = []
                for c in candidates:
                    kc = (c or '').strip().lower()
                    if not kc or kc in seen:
                        continue
                    seen.add(kc)
                    uniq.append(c)

                found = False
                for q in uniq:
                    try:
                        g_lat, g_lon = _geocode_query(q)
                        if g_lat is not None and g_lon is not None:
                            fallback_trips.append({'id': f'upload-{len(fallback_trips)+1}', 'lat': g_lat, 'lon': g_lon, 'label': ln, 'demand': 1, 'service_sec': 600, 'tw_start': 5*3600, 'tw_end': 17*3600})
                            found = True
                            break
                    except Exception:
                        continue
                # small delay to avoid hammering geocoder in tight loops
                if not found:
                    try:
                        time.sleep(0.1)
                    except Exception:
                        pass
            if fallback_trips:
                trips = fallback_trips
        if not trips:
            return jsonify({'error': 'no trips parsed'}), 400
        # insert driver (first trip as depot)
        depot = trips[0]
        drv = {'id': 'uploaded-depot-1', 'lat': depot['lat'], 'lon': depot['lon'], 'label': 'Uploaded depot', 'active': True}
        upsert_driver(drv)
        # insert trips
        for t in trips:
            upsert_trip(t)
        # refresh caches
        global _DRIVERS, _TRIPS
        _DRIVERS = get_all_drivers()
        _TRIPS = get_all_trips()
        msg = {'ok': True, 'inserted': len(trips)}
        if geocode_flag:
            msg['geocoded'] = True
        return jsonify(msg)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


def build_and_save_routes():
    """Build routes from current in-memory _TRIPS and _DRIVERS and write outputs using vrp_prototype.save_outputs.
    Returns a dict with assignments and filenames written.
    """
    # load persistent state from DB
    active_drivers = [d for d in get_all_drivers().values() if d.get('active', True)]
    trips = list(get_all_trips())
    assignments = {}
    per_driver_trips = {}
    # initialize per-driver assignment lists
    for drv in active_drivers:
        per_driver_trips[str(drv.get('id'))] = []

    # Improved assignment heuristic: incremental-cost insertion
    # For each trip, choose the driver whose route (when adding the trip and re-sequencing)
    # results in the smallest total route time. We solve a small single-vehicle VRP per candidate
    # (depot + existing assigned stops + candidate). To limit OR-Tools calls, we first rank
    # drivers by haversine distance to the trip and evaluate the top N candidates.
    if trips:
        try:
            top_n = int(os.environ.get('ASSIGN_EVAL_TOP_N', '3'))
        except Exception:
            top_n = 3

        # helper to compute route total seconds from a solved route and time matrix
        def route_total_seconds(route_nodes, tm, service_times):
            cur = 0
            total = 0
            for i in range(len(route_nodes) - 1):
                a = route_nodes[i]
                b = route_nodes[i + 1]
                travel = int(tm[a][b])
                srv = int(service_times[b]) if b < len(service_times) else 0
                arrival = cur + travel
                depart = arrival + srv
                cur = depart
                total = depart
            return int(total)

        remaining = list(trips)
        # iterate until no remaining trips
        while remaining:
            t = remaining.pop(0)
            best_driver = None
            best_cost = None

            # rank drivers by haversine to trip
            drv_scores = []
            for drv in active_drivers:
                drv_loc = (drv.get('lat'), drv.get('lon'))
                t_loc = (t.get('lat'), t.get('lon'))
                drv_scores.append((haversine(drv_loc, t_loc), drv))
            drv_scores.sort(key=lambda x: x[0])

            # evaluate top-N drivers (or all if fewer)
            eval_drivers = [d for _, d in drv_scores[:max(1, min(len(drv_scores), top_n))]]

            for drv in eval_drivers:
                drv_id = str(drv.get('id'))
                assigned = list(per_driver_trips.get(drv_id, []))
                # construct local stops: depot + existing assigned stops + candidate
                depot = vrp_prototype.STOPS[0]
                local_stops = [depot] + [(x.get('lat'), x.get('lon')) for x in assigned] + [(t.get('lat'), t.get('lon'))]
                # local service times: 0 at depot, use global default SERVICE_TIMES[0] for others if present
                local_service = [0] + [vrp_prototype.SERVICE_TIMES[0] if vrp_prototype.SERVICE_TIMES else 0 for _ in range(len(local_stops) - 1)]
                try:
                    local_tm = vrp_prototype.build_time_matrix(local_stops)
                    sub_routes = vrp_prototype.solve_vrp(
                        local_tm,
                        1,
                        0,
                        demands=[0] * len(local_stops),
                        vehicle_capacities=[999999],
                        service_times=local_service,
                        time_windows=[(0, vrp_prototype.SHIFT_SECONDS) for _ in local_stops],
                    )
                    if sub_routes and sub_routes[0]:
                        total = route_total_seconds(sub_routes[0], local_tm, local_service)
                        if best_cost is None or total < best_cost:
                            best_cost = total
                            best_driver = drv
                except Exception:
                    # fallback: approximate by haversine distance sum if OR-Tools fails
                    # compute naive cost: distance from depot->assigned->candidate->depot in km -> seconds at 50 km/h
                    try:
                        seq = [depot] + [(x.get('lat'), x.get('lon')) for x in assigned] + [(t.get('lat'), t.get('lon'))] + [depot]
                        approx_sec = 0
                        for i in range(len(seq) - 1):
                            km = vrp_prototype.haversine(seq[i], seq[i + 1])
                            approx_sec += int(km / 50.0 * 3600)
                        if best_cost is None or approx_sec < best_cost:
                            best_cost = approx_sec
                            best_driver = drv
                    except Exception:
                        continue

            if best_driver is None:
                # fallback to nearest-driver if everything else failed
                nearest = min(active_drivers, key=lambda d: haversine((d.get('lat'), d.get('lon')), (t.get('lat'), t.get('lon'))))
                per_driver_trips[str(nearest.get('id'))].append(t)
                assignments.setdefault(str(nearest.get('id')), {})['assigned_fallback'] = t.get('id')
            else:
                # record assignment and append to driver's assigned list
                per_driver_trips[str(best_driver.get('id'))].append(t)
                assignments.setdefault(str(best_driver.get('id')), {})['assigned_last'] = t.get('id')

        # remaining trips is empty now
        trips = []

    # For each driver, if they have multiple assigned trips, build a small VRP to sequence stops
    depot_coord = vrp_prototype.STOPS[0]
    all_routes = []
    all_stops = [depot_coord]
    # mapping from per-driver local index to global index
    for drv in active_drivers:
        drv_id = str(drv.get('id'))
        assigned = per_driver_trips.get(drv_id, [])
        if not assigned:
            # driver route only depot
            all_routes.append([0, 0])
            continue
        # build local stops: depot + assigned stops
        local_stops = [depot_coord] + [(t.get('lat'), t.get('lon')) for t in assigned]
        # simple demands/service times: use service time from vrp_prototype.SERVICE_TIMES if available, otherwise 0
        local_service = [0] + [vrp_prototype.SERVICE_TIMES[0] if len(vrp_prototype.SERVICE_TIMES) > 0 else 0 for _ in assigned]
        # build local time matrix
        local_tm = vrp_prototype.build_time_matrix(local_stops)
        # solve local VRP for single vehicle
        try:
            sub_routes = vrp_prototype.solve_vrp(local_tm, 1, 0, demands=[0]*(len(local_stops)), vehicle_capacities=[999999], service_times=local_service, time_windows=[(0, vrp_prototype.SHIFT_SECONDS) for _ in local_stops])
            # map sub_routes[0] back to global stop indices
            mapped = []
            for node in sub_routes[0]:
                if node == 0:
                    mapped.append(0)
                else:
                    # append new stop to global list
                    all_stops.append(local_stops[node])
                    mapped.append(len(all_stops) - 1)
            all_routes.append(mapped)
        except Exception:
            # fallback: greedy order
            route_idx = [0]
            for t in assigned:
                all_stops.append((t.get('lat'), t.get('lon')))
                route_idx.append(len(all_stops) - 1)
            route_idx.append(0)
            all_routes.append(route_idx)

    # Save final routes using vrp_prototype.save_outputs
    tm = vrp_prototype.build_time_matrix(all_stops)
    vrp_prototype.save_outputs(all_routes, all_stops, tm)
    remaining = [{'id': t.get('id'), 'lat': t.get('lat'), 'lon': t.get('lon')} for t in trips]
    return {'assignments': assignments, 'remaining': remaining, 'routes_written': len(all_routes)}


def build_preview():
    """Build a preview of assignments and sequenced routes without writing files.
    Returns a dict with assignments, per-driver routes (lists of stop coords and eta estimates), and remaining trips.
    """
    # load from DB as source of truth
    active_drivers = [d for d in get_all_drivers().values() if d.get('active', True)]
    trips = list(get_all_trips())
    assignments = {}
    per_driver_trips = {str(d.get('id')): [] for d in active_drivers}

    # Use the same improved insertion heuristic implemented above (inline to avoid refactor)
    if trips:
        try:
            top_n = int(os.environ.get('ASSIGN_EVAL_TOP_N', '3'))
        except Exception:
            top_n = 3

        def route_total_seconds(route_nodes, tm, service_times):
            cur = 0
            total = 0
            for i in range(len(route_nodes) - 1):
                a = route_nodes[i]
                b = route_nodes[i + 1]
                travel = int(tm[a][b])
                srv = int(service_times[b]) if b < len(service_times) else 0
                arrival = cur + travel
                depart = arrival + srv
                cur = depart
                total = depart
            return int(total)

        remaining = list(trips)
        while remaining:
            t = remaining.pop(0)
            best_driver = None
            best_cost = None

            drv_scores = []
            for drv in active_drivers:
                drv_loc = (drv.get('lat'), drv.get('lon'))
                t_loc = (t.get('lat'), t.get('lon'))
                drv_scores.append((haversine(drv_loc, t_loc), drv))
            drv_scores.sort(key=lambda x: x[0])
            eval_drivers = [d for _, d in drv_scores[:max(1, min(len(drv_scores), top_n))]]

            for drv in eval_drivers:
                drv_id = str(drv.get('id'))
                assigned = list(per_driver_trips.get(drv_id, []))
                depot = vrp_prototype.STOPS[0]
                local_stops = [depot] + [(x.get('lat'), x.get('lon')) for x in assigned] + [(t.get('lat'), t.get('lon'))]
                local_service = [0] + [vrp_prototype.SERVICE_TIMES[0] if vrp_prototype.SERVICE_TIMES else 0 for _ in range(len(local_stops) - 1)]
                try:
                    local_tm = vrp_prototype.build_time_matrix(local_stops)
                    sub_routes = vrp_prototype.solve_vrp(local_tm, 1, 0, demands=[0] * len(local_stops), vehicle_capacities=[999999], service_times=local_service, time_windows=[(0, vrp_prototype.SHIFT_SECONDS) for _ in local_stops])
                    if sub_routes and sub_routes[0]:
                        total = route_total_seconds(sub_routes[0], local_tm, local_service)
                        if best_cost is None or total < best_cost:
                            best_cost = total
                            best_driver = drv
                except Exception:
                    try:
                        seq = [depot] + [(x.get('lat'), x.get('lon')) for x in assigned] + [(t.get('lat'), t.get('lon'))] + [depot]
                        approx_sec = 0
                        for i in range(len(seq) - 1):
                            km = vrp_prototype.haversine(seq[i], seq[i + 1])
                            approx_sec += int(km / 50.0 * 3600)
                        if best_cost is None or approx_sec < best_cost:
                            best_cost = approx_sec
                            best_driver = drv
                    except Exception:
                        continue

            if best_driver is None:
                nearest = min(active_drivers, key=lambda d: haversine((d.get('lat'), d.get('lon')), (t.get('lat'), t.get('lon'))))
                per_driver_trips[str(nearest.get('id'))].append(t)
                assignments.setdefault(str(nearest.get('id')), {})['assigned_fallback'] = t.get('id')
            else:
                per_driver_trips[str(best_driver.get('id'))].append(t)
                assignments.setdefault(str(best_driver.get('id')), {})['assigned_last'] = t.get('id')

        trips = []

    # Now sequence per-driver assigned stops (but do not write files)
    depot_coord = vrp_prototype.STOPS[0]
    preview_routes = {}
    per_driver_trip_ids = {}
    for drv in active_drivers:
        drv_id = str(drv.get('id'))
        assigned = per_driver_trips.get(drv_id, [])
        if not assigned:
            preview_routes[drv_id] = {'route': [depot_coord, depot_coord], 'stops': []}
            per_driver_trip_ids[drv_id] = []
            continue
        local_stops = [depot_coord] + [(t.get('lat'), t.get('lon')) for t in assigned]
        local_service = [0] + [vrp_prototype.SERVICE_TIMES[0] if vrp_prototype.SERVICE_TIMES else 0 for _ in assigned]
        try:
            local_tm = vrp_prototype.build_time_matrix(local_stops)
            sub_routes = vrp_prototype.solve_vrp(local_tm, 1, 0, demands=[0] * len(local_stops), vehicle_capacities=[999999], service_times=local_service, time_windows=[(0, vrp_prototype.SHIFT_SECONDS) for _ in local_stops])
            seq = sub_routes[0]
            # build per-stop ETA estimates
            cur = 0
            stops_info = []
            for i in range(len(seq) - 1):
                a = seq[i]
                b = seq[i + 1]
                travel = int(local_tm[a][b])
                srv = int(local_service[b]) if b < len(local_service) else 0
                arrival = cur + travel
                depart = arrival + srv
                # try to attach trip id/label for non-depot stops
                trip_id = None
                label = None
                if b > 0 and b - 1 < len(assigned):
                    try:
                        tinfo = assigned[b - 1]
                        trip_id = tinfo.get('id')
                        label = tinfo.get('stop') or tinfo.get('label') or trip_id
                    except Exception:
                        trip_id = None
                        label = None

                def sec_to_hhmm(s):
                    try:
                        s = int(s)
                        h = s // 3600
                        m = (s % 3600) // 60
                        return f"{h:02d}:{m:02d}"
                    except Exception:
                        return ''

                stops_info.append({'sequence': i + 1, 'stop_index': b, 'lat': local_stops[b][0], 'lon': local_stops[b][1], 'eta_sec': int(arrival), 'depart_sec': int(depart), 'eta_hhmm': sec_to_hhmm(arrival), 'depart_hhmm': sec_to_hhmm(depart), 'service_sec': srv, 'trip_id': trip_id, 'label': label})
                cur = depart
            preview_routes[drv_id] = {'route': [local_stops[i] for i in seq], 'stops': stops_info}
            per_driver_trip_ids[drv_id] = [t.get('id') for t in assigned]
        except Exception:
            # fallback greedy order
            seq_idx = [0]
            for t in assigned:
                seq_idx.append(len(seq_idx))
            seq_idx.append(0)
            preview_routes[drv_id] = {'route': [depot_coord] + [(t.get('lat'), t.get('lon')) for t in assigned] + [depot_coord], 'stops': []}
            per_driver_trip_ids[drv_id] = [t.get('id') for t in assigned]

    remaining_preview = [{'id': t.get('id'), 'lat': t.get('lat'), 'lon': t.get('lon')} for t in get_all_trips() if t not in [it for sub in per_driver_trips.values() for it in sub]]
    return {'assignments': assignments, 'preview_routes': preview_routes, 'per_driver_trip_ids': per_driver_trip_ids, 'remaining': remaining_preview}


@app.route('/api/build_routes', methods=['POST'])
@require_token
def api_build_routes():
    try:
        res = build_and_save_routes()
        return jsonify({'ok': True, 'result': res})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/live_status', methods=['GET'])
def api_live_status():
    """Return a snapshot of current drivers and trips for live UI polling.
    This is public GET (no token) to allow the UI to poll frequently.
    """
    try:
        drivers = list(get_all_drivers().values())
        trips = list(get_all_trips())
        return jsonify({'ok': True, 'drivers': drivers, 'trips': trips, 'timestamp': time.time()})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/mapping_pref', methods=['GET'])
def api_get_mapping_pref():
    try:
        pid = flask_request.args.get('id')
        if not pid:
            return jsonify({'error': 'id required'}), 400
        pref = get_mapping_pref(pid)
        return jsonify({'ok': True, 'pref': pref})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/mapping_pref', methods=['POST'])
@require_token
def api_set_mapping_pref():
    try:
        payload = __import__('flask').request.get_json(force=True) or {}
        pid = payload.get('id')
        mapping = payload.get('pref') or payload.get('payload') or payload.get('mapping')
        if not pid or mapping is None:
            return jsonify({'error': 'id and pref required'}), 400
        upsert_mapping_pref({'id': pid, 'payload': mapping, 'updated_at': time.time()})
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# Lightweight health endpoint for readiness/liveness checks
@app.route('/healthz', methods=['GET'])
def healthz():
    try:
        init_db()
        return jsonify({'status': 'ok'}), 200
    except Exception as e:
        return jsonify({'status': 'error', 'detail': str(e)}), 500


@app.route('/api/preview', methods=['POST'])
@require_token
def api_preview():
    try:
        # If a pre-baked preview file exists (preview_sample.json), return it immediately.
        # This is useful for demoing the UI without running the full OR-Tools solve.
        # Check for demo or watcher-generated previews so the UI can show them immediately
        demo_path = os.path.join('.', 'preview_sample.json')
        watch_path = os.path.join('.', 'preview.json')
        for sample_path in (demo_path, watch_path):
            if os.path.exists(sample_path):
                try:
                    with open(sample_path) as sf:
                        payload = json.load(sf)
                    return jsonify({'ok': True, 'result': payload})
                except Exception:
                    # fall through to next option or live build_preview on parse error
                    pass
        res = build_preview()
        return jsonify({'ok': True, 'result': res})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/apply_preview', methods=['POST'])
@require_token
def api_apply_preview():
    """Apply a preview: accepts optional preview payload (assignments and per_driver_trip_ids).
    If none provided, recomputes preview. Commits routes by writing outputs and removing applied trips from DB.
    """
    try:
        payload = __import__('flask').request.get_json(force=True) or {}
        if payload and isinstance(payload, dict) and 'result' in payload:
            preview = payload['result']
        else:
            preview = build_preview()

        per_driver_ids = preview.get('per_driver_trip_ids', {})
        active_drivers = [d for d in get_all_drivers().values() if d.get('active', True)]

        depot_coord = vrp_prototype.STOPS[0]
        all_routes = []
        all_stops = [depot_coord]

        # For each driver, map trip ids to coords and sequence via OR-Tools
        for drv in active_drivers:
            drv_id = str(drv.get('id'))
            ids = per_driver_ids.get(drv_id, [])
            if not ids:
                all_routes.append([0, 0])
                continue
            assigned = [get_trip_by_id(tid) for tid in ids]
            assigned = [t for t in assigned if t]
            if not assigned:
                all_routes.append([0, 0])
                continue
            local_stops = [depot_coord] + [(t.get('lat'), t.get('lon')) for t in assigned]
            local_service = [0] + [vrp_prototype.SERVICE_TIMES[0] if vrp_prototype.SERVICE_TIMES else 0 for _ in assigned]
            try:
                local_tm = vrp_prototype.build_time_matrix(local_stops)
                sub_routes = vrp_prototype.solve_vrp(local_tm, 1, 0, demands=[0] * len(local_stops), vehicle_capacities=[999999], service_times=local_service, time_windows=[(0, vrp_prototype.SHIFT_SECONDS) for _ in local_stops])
                mapped = []
                for node in sub_routes[0]:
                    if node == 0:
                        mapped.append(0)
                    else:
                        all_stops.append(local_stops[node])
                        mapped.append(len(all_stops) - 1)
                all_routes.append(mapped)
            except Exception:
                # fallback greedy
                route_idx = [0]
                for t in assigned:
                    all_stops.append((t.get('lat'), t.get('lon')))
                    route_idx.append(len(all_stops) - 1)
                route_idx.append(0)
                all_routes.append(route_idx)

        # write outputs
        tm = vrp_prototype.build_time_matrix(all_stops)
        vrp_prototype.save_outputs(all_routes, all_stops, tm)

        # archive applied trips and record preview audit
        applied_ids = [tid for sub in per_driver_ids.values() for tid in sub]
        try:
            archive_trips_and_record_preview(applied_ids, preview)
        except Exception:
            pass

        # refresh caches
        global _TRIPS, _DRIVERS
        _TRIPS = get_all_trips()
        _DRIVERS = get_all_drivers()

        return jsonify({'ok': True, 'routes_written': len(all_routes), 'applied_trip_count': len(applied_ids)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


INDEX_HTML = r"""
<!doctype html>
<html>
<head>
    <meta charset="utf-8" />
    <title>Routes Summary</title>
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" integrity="sha256-sA+e2Yq0b4o6Q6vJt0YI6GQ3q6q9bQKxQ6pVg9m2h3o=" crossorigin=""/>
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js" integrity="sha256-o9N1j7Lk6b0m6a1b7rJ7s6m3k6l9s8m3q9pVg9m2h3o=" crossorigin=""></script>
    <style>
        table { border-collapse: collapse; width: 100%; }
        th, td { border: 1px solid #ddd; padding: 8px; }
        tr:nth-child(even){background-color: #f2f2f2}
        th { background-color: #4CAF50; color: white; }
        .stops { display: none; margin: 8px 0 16px 0; }
        .btn { cursor: pointer; color: blue; text-decoration: underline; }
        #previewMap { height: 400px; margin-top: 8px; display: none; }
        #previewPanel { margin-top: 16px; padding: 8px; border: 1px solid #ccc; background: #fafafa }
        pre { max-height: 240px; overflow: auto; background: #f6f6f6; padding: 8px }
    </style>
    </head>
<body>
<h1>Routes Summary</h1>
<p>
    <a href="/map">Open Map</a> |
    <a href="/routes.json">Raw routes.json</a> |
    <a href="/debug">Cluster debug</a>
</p>
<div style="margin-top:10px;display:flex;gap:12px;align-items:center;">
    <label style="display:flex;gap:6px;align-items:center"><input type="checkbox" id="liveToggle" /> Live</label>
    <div id="liveStatus" style="font-size:0.95rem;color:#444">Live: off</div>
</div>

<h2>Route summary</h2>
<div style="display:flex;gap:12px;align-items:flex-start;">
    <div style="flex:1">
        <div id="summary">Loading...</div>
    </div>
    <div id="sidebar" style="width:320px;background:#fff;border:1px solid #ddd;padding:8px;max-height:560px;overflow:auto;position:relative">
        <div style="display:flex;gap:6px;align-items:center;margin-bottom:6px;">
            <input id="sidebarSearch" placeholder="Search stops" style="flex:1;padding:6px" />
            <button id="clearSearch">Clear</button>
        </div>
        <div style="display:flex;gap:6px;margin-bottom:6px;align-items:center">
            <button id="toggleSidebar">Collapse</button>
            <button id="downloadCSV">Download stops CSV</button>
            <button id="copyAll">Copy all labels</button>
        </div>
        <div id="stopList">Loading stops...</div>
    </div>
</div>

<h2>Assignments / Auto-suggest</h2>
<div>
    <label>API token: <input id="token" type="password" /></label>
    <button id="fetchSuggest">Get Suggestions</button>
    <pre id="suggestions"></pre>
</div>

<h2>Preview Panel</h2>
<div id="previewPanel">
    <div style="display:flex;gap:8px;align-items:center;">
        <div>
            <label>API token: <input id="tokenPreview" type="password" /></label>
            <button id="fetchPreview">Get Preview</button>
            <button id="applyPreview">Apply Preview</button>
        </div>
        <div style="flex:1">
            <strong>Quick paste/upload (managers)</strong>
            <p style="margin:0">Paste JSON arrays of <code>drivers</code> or <code>trips</code> and click Upload to POST to the API (keeps DB in sync).</p>
            <div style="display:flex;gap:8px;margin-top:4px;">
                <textarea id="pasteDrivers" placeholder='[{"id":"drv1","lat":..}]' style="width:50%;height:80px"></textarea>
                <textarea id="pasteTrips" placeholder='[{"id":"trip1","lat":..}]' style="width:50%;height:80px"></textarea>
            </div>
            <div style="margin-top:6px"><button id="uploadPasted">Upload pasted drivers & trips</button> <span id="uploadStatus"></span></div>
            <div style="margin-top:8px;border-top:1px solid #eee;padding-top:8px">
                <div><strong>Import CSV file</strong> — select a CSV/TSV file with columns (lat, lon, address) or freeform rows containing coordinates.</div>
                <input id="csvFileInput" type="file" accept=".csv,.tsv,text/csv,text/tab-separated-values" style="margin-top:6px" />
                <div id="csvMapping" style="margin-top:6px;display:none">
                    <div style="margin-top:6px">Detected columns: <span id="detectedCols"></span></div>
                    <div style="margin-top:6px">Map columns: Lat: <select id="mapLat"></select> Lon: <select id="mapLon"></select> Label: <select id="mapLabel"></select></div>
                    <div style="margin-top:6px;display:flex;gap:8px;align-items:center">
                        <button id="saveMapping">Save mapping</button>
                        <button id="loadMapping">Load mapping</button>
                        <span id="mappingStatus" style="margin-left:8px;color:#444"></span>
                    </div>
                </div>
                <div style="margin-top:6px"><button id="importCsvBtn">Import CSV to API</button> <span id="importStatus"></span></div>
                <div style="margin-top:6px"><label style="margin-left:6px"><input type="checkbox" id="geocodeCheckbox" /> Attempt geocode for missing coords</label></div>
            </div>
        </div>
    </div>
    <div id="previewMeta"><em>No preview yet</em></div>
    <div id="previewMap"></div>
    <div style="margin-top:8px"><strong>Legend:</strong> <span id="legend"></span></div>
    <h3>Preview JSON</h3>
    <pre id="previewResult">(preview will appear here)</pre>
</div>

<!-- Confirmation modal -->
<div id="confirmModal" style="display:none;position:fixed;left:0;top:0;width:100%;height:100%;background:rgba(0,0,0,0.4);align-items:center;justify-content:center;">
    <div style="background:#fff;padding:16px;border-radius:6px;max-width:520px;margin:auto;">
        <h3>Confirm Apply Preview</h3>
        <div id="confirmBody">Preparing...</div>
            <div style="margin-top:8px;">
                <label>Type password to confirm: <input id="confirmPassword" type="password" style="margin-left:8px" /></label>
                <div style="font-size:12px;color:#666;margin-top:6px">(Password required: <code>1</code>)</div>
            </div>
            <div style="margin-top:12px;text-align:right;">
                <button id="confirmCancel">Cancel</button>
                <button id="confirmOk" disabled style="margin-left:8px;background:#c33;color:#fff">Confirm Apply</button>
            </div>
    </div>
</div>

<script>
async function loadRoutes(){
    const el = document.getElementById('summary');
    try{
        const resp = await fetch('/routes.json');
        if(!resp.ok){ el.textContent = 'routes.json not found'; return }
        const data = await resp.json();
        if(!Array.isArray(data) || data.length === 0){ el.textContent = 'No routes available'; return }
        let html = '<table><thead><tr><th>Vehicle</th><th>Total hours</th><th>Total seconds</th><th>Violates shift</th><th>CSV</th><th>Details</th></tr></thead><tbody>'
        data.forEach(r => {
            const vid = r.vehicle || r.vehicle;
            const th = r.total_hours ?? '';
            const ts = r.total_seconds ?? '';
            const vs = r.violates_shift ? 'YES' : 'no';
            const csv = `route_vehicle_${vid}.csv`;
            html += `<tr><td>${vid}</td><td>${th}</td><td>${ts}</td><td>${vs}</td><td><a href='/download/${csv}'>${csv}</a></td><td><span class='btn' data-vid='${vid}'>toggle</span></td></tr>`;
            // hidden stops table
            html += `<tr class='stops' id='stops-${vid}'><td colspan='6'><table><thead><tr><th>#</th><th>stop</th><th>lat</th><th>lon</th><th>eta</th><th>depart</th><th>service(s)</th></tr></thead><tbody>`;
            (r.stops || []).forEach(s => {
                html += `<tr><td>${s.sequence}</td><td>${s.stop}</td><td>${s.lat}</td><td>${s.lon}</td><td>${s.eta_hhmm || s.eta_sec || ''}</td><td>${s.depart_hhmm || s.depart_sec || ''}</td><td>${s.service_sec || ''}</td></tr>`;
            });
            html += '</tbody></table></td></tr>';
        });
        html += '</tbody></table>';
        el.innerHTML = html;
        document.querySelectorAll('.btn').forEach(b => {
            b.onclick = () => {
                const vid = b.getAttribute('data-vid');
                const row = document.getElementById('stops-' + vid);
                if(row.style.display === 'table-row') row.style.display = 'none'; else row.style.display = 'table-row';
            }
        });
    }catch(e){ el.textContent = 'Error loading routes: ' + e }
}
window.addEventListener('load', loadRoutes);

// Preview panel logic
let previewData = null;
let previewMap = null;
let previewLayerGroup = null;
const colors = ['red','blue','green','purple','orange','darkred','cadetblue'];

function ensurePreviewMap(){
    if(previewMap) return previewMap;
    const el = document.getElementById('previewMap');
    el.style.display = 'block';
    previewMap = L.map('previewMap').setView([0,0], 11);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {maxZoom:19}).addTo(previewMap);
    previewLayerGroup = L.featureGroup().addTo(previewMap);
    return previewMap;
}

function clearPreviewMap(){
    if(previewLayerGroup){ previewLayerGroup.clearLayers(); }
}

async function fetchPreview(){
    const token = document.getElementById('tokenPreview').value;
    const out = document.getElementById('previewResult');
    const meta = document.getElementById('previewMeta');
    out.textContent = 'Loading...';
    meta.textContent = '';
    try{
        const resp = await fetch('/api/preview', {method:'POST', headers: {'Content-Type':'application/json', 'X-API-Token': token}, body: JSON.stringify({})});
        if(!resp.ok){ out.textContent = 'Error: ' + resp.status; return }
        const data = await resp.json();
        if(!data || !data.result){ out.textContent = JSON.stringify(data, null, 2); return }
        previewData = data.result;
        out.textContent = JSON.stringify(previewData, null, 2);
        meta.textContent = `Assigned drivers: ${Object.keys(previewData.per_driver_trip_ids || {}).length}, Remaining: ${ (previewData.remaining || []).length }`;

    // draw on map
        const map = ensurePreviewMap();
        clearPreviewMap();
        const prs = previewData.preview_routes || {};
        let firstLatLng = null;
        let idx = 0;
        for(const [drv, pr] of Object.entries(prs)){
            const route = pr.route || [];
            if(route.length < 2) continue;
            const latlngs = route.map(r => [r[0], r[1]]);
            if(!firstLatLng) firstLatLng = latlngs[0];
            const poly = L.polyline(latlngs, {color: colors[idx % colors.length], weight:4}).addTo(previewLayerGroup);
            // draw markers with enriched popups using preview_routes.stops info when available
            const stopsInfo = pr.stops || [];
            latlngs.forEach((ll,i)=>{
                let popupHtml = `<b>Driver ${drv}</b><br>#${i+1}`;
                const stopInfo = stopsInfo[i] || stopsInfo.find(s => s.sequence === (i+1));
                if(stopInfo){
                    const label = stopInfo.label || stopInfo.trip_id || '';
                    const eta = stopInfo.eta_hhmm || stopInfo.eta_sec || '';
                    const depart = stopInfo.depart_hhmm || stopInfo.depart_sec || '';
                    const svc = stopInfo.service_sec || '';
                    popupHtml += `<br><b>${label}</b>`;
                    popupHtml += `<br>ETA: ${eta} &nbsp; Depart: ${depart}`;
                    if(svc) popupHtml += `<br>Service: ${svc}s`;
                    if(stopInfo.trip_id) popupHtml += `<br>ID: ${stopInfo.trip_id}`;
                    // copy-to-clipboard button
                    popupHtml += `<br><button class='copyLabel' data-label='${(label || '').replace(/'/g, "\\'") }'>Copy label</button>`;
                }
                // numbered DivIcon marker
                const number = i+1;
                const color = colors[idx % colors.length];
                const icon = L.divIcon({className: 'num-icon', html: `<div style="background:${color};color:#fff;border-radius:12px;padding:2px 6px;font-weight:bold">${number}</div>`, iconSize: [24,24]});
                const marker = L.marker(ll, {icon: icon}).bindPopup(popupHtml).addTo(previewLayerGroup);
                marker.on('popupopen', (ev)=>{
                    const btn = ev.popup._contentNode.querySelector('.copyLabel');
                    if(btn){ btn.onclick = ()=>{ navigator.clipboard.writeText(btn.getAttribute('data-label') || ''); alert('Copied'); } }
                });
            });
            // add legend entry for this driver
            const legend = document.getElementById('legend');
            const legendItem = document.createElement('span');
            legendItem.style.marginRight = '12px';
            legendItem.innerHTML = `<span style="display:inline-block;width:12px;height:12px;background:${colors[idx % colors.length]};margin-right:6px;vertical-align:middle"></span>Driver ${drv}`;
            legend.appendChild(legendItem);
            idx += 1;
        }
        if(firstLatLng){ previewMap.setView(firstLatLng, 12); }
    // populate sidebar stop list (flatten stops across drivers)
        const stopList = document.getElementById('stopList');
        stopList.innerHTML = '';
        const flatStops = [];
        Object.values(prs).forEach((pr, drvIdx)=>{
            (pr.stops || []).forEach(s=>{
                flatStops.push({driver: drvIdx+1, sequence: s.sequence, label: s.label || s.trip_id || '', lat: s[0] || s.lat, lon: s[1] || s.lon});
            });
        });
        if(flatStops.length === 0) stopList.innerHTML = '<em>No stops in preview</em>';
        flatStops.forEach((s, i)=>{
            const div = document.createElement('div');
            div.className = 'stopItem';
            div.style.borderBottom = '1px solid #eee';
            div.style.padding = '6px';
            div.innerHTML = `<div style='font-weight:600'>#${s.sequence} <small style='color:#666'>Driver ${s.driver}</small></div><div style='font-size:13px;word-break:break-word' title='${(s.label||'').replace(/'/g, "\\'")}'>${s.label}</div><div style='font-size:12px;color:#666'>${s.lat || ''}, ${s.lon || ''}</div>`;
            div.onclick = ()=>{ previewMap.setView([s.lat || 0, s.lon || 0], 15); }
            stopList.appendChild(div);
        });
        // download CSV
        document.getElementById('downloadCSV').onclick = ()=>{
            const rows = ['sequence,driver,label,lat,lon'];
            flatStops.forEach(s=> rows.push(`${s.sequence},${s.driver},"${(s.label||'').replace(/"/g,'""')}",${s.lat||''},${s.lon||''}`));
            const blob = new Blob([rows.join('\n')], {type:'text/csv;charset=utf-8;'});
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a'); a.href = url; a.download = 'preview_stops.csv'; document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url);
        };
        // copy all labels
        document.getElementById('copyAll').onclick = ()=>{
            const all = flatStops.map(s=>s.label).filter(Boolean).join('\n');
            navigator.clipboard.writeText(all).then(()=>{ alert('Copied ' + flatStops.length + ' labels'); }).catch(()=>{ alert('Copy failed'); });
        };
        // sidebar collapse
        const sb = document.getElementById('sidebar');
        const toggle = document.getElementById('toggleSidebar');
        toggle.onclick = ()=>{
            if(sb.style.width === '40px'){
                sb.style.width = '320px'; toggle.textContent = 'Collapse'; document.getElementById('stopList').style.display = 'block';
            } else { sb.style.width = '40px'; toggle.textContent = 'Expand'; document.getElementById('stopList').style.display = 'none'; }
        };
        // search behavior
        document.getElementById('sidebarSearch').oninput = (ev)=>{
            const q = ev.target.value.toLowerCase();
            document.querySelectorAll('#stopList .stopItem').forEach(item=>{
                item.style.display = (q === '' || item.textContent.toLowerCase().indexOf(q) !== -1) ? 'block' : 'none';
            });
        };
        document.getElementById('clearSearch').onclick = ()=>{ document.getElementById('sidebarSearch').value=''; document.getElementById('sidebarSearch').dispatchEvent(new Event('input')); };
    }catch(err){ out.textContent = 'Request failed: ' + err }
}

async function applyPreview(){
    if(!previewData){ alert('No preview available; fetch preview first'); return }
    const token = document.getElementById('tokenPreview').value;
    const out = document.getElementById('previewResult');
    out.textContent = 'Applying preview...';
    try{
        const resp = await fetch('/api/apply_preview', {method:'POST', headers: {'Content-Type':'application/json', 'X-API-Token': token}, body: JSON.stringify({result: previewData})});
        const data = await resp.json();
        if(!resp.ok){ out.textContent = 'Apply error: ' + JSON.stringify(data); return }
        out.textContent = 'Apply result: ' + JSON.stringify(data, null, 2);
        // refresh summary
        await loadRoutes();
    }catch(err){ out.textContent = 'Apply failed: ' + err }
}

document.getElementById('fetchPreview').onclick = fetchPreview;
document.getElementById('applyPreview').onclick = () => {
    // open confirm modal and populate summary
    const modal = document.getElementById('confirmModal');
    const body = document.getElementById('confirmBody');
    if(!previewData){ alert('No preview available; fetch preview first'); return }
    const assigned = previewData.per_driver_trip_ids || {};
    const assignedDrivers = Object.keys(assigned).length;
    const assignedTrips = Object.values(assigned).reduce((s, arr) => s + (arr ? arr.length : 0), 0);
    body.innerHTML = `<p>This will apply the preview to <b>${assignedDrivers}</b> driver(s) and archive <b>${assignedTrips}</b> trip(s).</p><p>Are you sure?</p>`;
    modal.style.display = 'flex';
};

document.getElementById('uploadPasted').onclick = async () => {
    const token = document.getElementById('tokenPreview').value;
    const drvTxt = document.getElementById('pasteDrivers').value.trim();
    const tripTxt = document.getElementById('pasteTrips').value.trim();
    const status = document.getElementById('uploadStatus');
    status.textContent = '';
    try{
        if(drvTxt){
            let djson = JSON.parse(drvTxt);
            if(!Array.isArray(djson)) djson = [djson];
            const resp = await fetch('/api/drivers', {method:'POST', headers:{'Content-Type':'application/json','X-API-Token': token}, body: JSON.stringify({drivers: djson})});
            const r = await resp.json();
            if(!resp.ok) throw new Error('drivers upload failed: ' + JSON.stringify(r));
            status.textContent = `Drivers uploaded: ${r.count || ''}`;
        }
        if(tripTxt){
            let tjson = JSON.parse(tripTxt);
            if(!Array.isArray(tjson)) tjson = [tjson];
            const resp2 = await fetch('/api/trips', {method:'POST', headers:{'Content-Type':'application/json','X-API-Token': token}, body: JSON.stringify({trips: tjson})});
            const r2 = await resp2.json();
            if(!resp2.ok) throw new Error('trips upload failed: ' + JSON.stringify(r2));
            status.textContent = (status.textContent ? status.textContent + '; ' : '') + `Trips uploaded: ${r2.count || ''}`;
        }
        // refresh preview metadata and summary
        await loadRoutes();
    }catch(err){ status.textContent = 'Upload error: ' + err }
};

// modal button handlers
document.getElementById('confirmCancel').onclick = () => {
    document.getElementById('confirmModal').style.display = 'none';
};
document.getElementById('confirmOk').onclick = async () => {
    document.getElementById('confirmModal').style.display = 'none';
    await applyPreview();
    // close modal then refresh preview panel
    try{ await fetchPreview(); }catch(e){}
};

// enable confirm button only when password equals '1'
const pwd = document.getElementById('confirmPassword');
const confirmBtn = document.getElementById('confirmOk');
if(pwd){
    pwd.addEventListener('input', () => {
        if(pwd.value === '1'){
            confirmBtn.removeAttribute('disabled');
        } else {
            confirmBtn.setAttribute('disabled', 'true');
        }
    });
}

document.addEventListener('click', async (e) => {
    if (e.target && e.target.id === 'fetchSuggest'){
        const token = document.getElementById('token').value;
        const out = document.getElementById('suggestions');
        out.textContent = 'Loading...';
        try{
            const resp = await fetch('/api/suggest', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-API-Token': token}, body: JSON.stringify({})});
            if (!resp.ok){ out.textContent = 'Error: ' + resp.status; return }
            const data = await resp.json();
            out.textContent = JSON.stringify(data, null, 2);
        }catch(err){ out.textContent = 'Request failed: ' + err }
    }
});

// Mapping prefs save/load handlers
document.getElementById('saveMapping').onclick = async () => {
    const token = document.getElementById('tokenPreview').value;
    const mapLat = document.getElementById('mapLat').value;
    const mapLon = document.getElementById('mapLon').value;
    const mapLabel = document.getElementById('mapLabel').value;
    const status = document.getElementById('mappingStatus');
    status.textContent = '';
    if(!token){ status.textContent = 'Enter API token above to save mapping'; return }
    const payload = {id: token, pref: {lat: isNaN(Number(mapLat)) ? mapLat : Number(mapLat), lon: isNaN(Number(mapLon)) ? mapLon : Number(mapLon), label: isNaN(Number(mapLabel)) ? mapLabel : Number(mapLabel)} };
    try{
        const resp = await fetch('/api/mapping_pref', {method: 'POST', headers: {'Content-Type':'application/json','X-API-Token': token}, body: JSON.stringify(payload)});
        const j = await resp.json();
        if(!resp.ok) throw new Error(JSON.stringify(j));
        status.textContent = 'Saved';
    }catch(err){ status.textContent = 'Save failed: ' + err }
};

document.getElementById('loadMapping').onclick = async () => {
    const token = document.getElementById('tokenPreview').value;
    const status = document.getElementById('mappingStatus');
    status.textContent = '';
    if(!token){ status.textContent = 'Enter API token above to load mapping'; return }
    try{
        const resp = await fetch('/api/mapping_pref?id=' + encodeURIComponent(token));
        const j = await resp.json();
        if(!resp.ok) throw new Error(JSON.stringify(j));
        const pref = j.pref || {};
        if(pref.lat !== undefined) document.getElementById('mapLat').value = pref.lat;
        if(pref.lon !== undefined) document.getElementById('mapLon').value = pref.lon;
        if(pref.label !== undefined) document.getElementById('mapLabel').value = pref.label;
        status.textContent = 'Loaded';
    }catch(err){ status.textContent = 'Load failed: ' + err }
};

// CSV import handler: parse simple CSV/TSV client-side and POST to API
document.getElementById('importCsvBtn').onclick = async () => {
    const f = document.getElementById('csvFileInput').files[0];
    const status = document.getElementById('importStatus');
    const token = document.getElementById('tokenPreview').value;
    status.textContent = '';
    if(!f){ status.textContent = 'No file selected'; return }
    try{
        // If mapping selects are visible, perform a FormData upload to /api/upload_csv
        const mappingEl = document.getElementById('csvMapping');
        if(mappingEl && mappingEl.style.display !== 'none'){
            const selLat = document.getElementById('mapLat').value;
            const selLon = document.getElementById('mapLon').value;
            const selLabel = document.getElementById('mapLabel').value;
            const mapping = {};
            if(selLat) mapping.lat = isNaN(Number(selLat)) ? selLat : Number(selLat);
            if(selLon) mapping.lon = isNaN(Number(selLon)) ? selLon : Number(selLon);
            if(selLabel) mapping.label = isNaN(Number(selLabel)) ? selLabel : Number(selLabel);
            const fd = new FormData();
            fd.append('file', f, f.name);
            fd.append('mapping', JSON.stringify(mapping));
            // include geocode flag if requested
            const geocodeChecked = document.getElementById('geocodeCheckbox') && document.getElementById('geocodeCheckbox').checked;
            if(geocodeChecked) fd.append('geocode', '1');
            const resp = await fetch('/api/upload_csv', {method:'POST', headers: {'X-API-Token': token}, body: fd});
            const jr = await resp.json();
            if(!resp.ok) throw new Error('upload failed: ' + JSON.stringify(jr));
            status.textContent = `Imported ${jr.inserted || 0} trips (server)`;
            await loadRoutes();
            return;
        }
        // fallback: previous client-side parsing + posts
        const text = await f.text();
        // try to detect delimiter
        const sample = text.slice(0, 2000);
        const delim = sample.indexOf('\t') !== -1 ? '\t' : (sample.indexOf(',') !== -1 ? ',' : null);
        const lines = text.split(/\r?\n/).map(s=>s.trim()).filter(Boolean);
        let rows = lines.map(l => delim ? l.split(delim).map(c=>c.trim()) : l.split(/\s+/));
        // detect header
        let headers = null;
        if(rows.length && rows[0].some(h=>/lat|lon|lng|latitude|longitude|address|addr|label/i.test(h))){
            headers = rows.shift().map(h=>h.toLowerCase());
        }
        const trips = [];
        const drivers = [];
        let idc = 1;
        for(const r of rows){
            let lat=null, lon=null, label='';
            if(headers){
                for(let i=0;i<r.length;i++){
                    const h = headers[i]||'';
                    if(/lat|latitude/i.test(h)) lat = parseFloat(r[i]) || lat;
                    if(/lon|lng|longitude/i.test(h)) lon = parseFloat(r[i]) || lon;
                    if(/addr|address|label|stop/i.test(h)) label = label ? label + ' ' + r[i] : r[i];
                }
            } else {
                // attempt to parse first two numeric tokens as lat/lon
                const nums = r.join(' ').match(/-?\d+\.\d+/g) || [];
                if(nums.length >= 2){ lat = parseFloat(nums[0]); lon = parseFloat(nums[1]); }
                // remaining text as label
                label = r.join(' ').replace(/-?\d+\.\d+/g,'').trim();
            }
            if(lat !== null && lon !== null){
                trips.push({id: 'csv-'+(idc++), lat: lat, lon: lon, label: label, demand:1, service_sec:600, tw_start:5*3600, tw_end:17*3600});
            }
        }
        if(trips.length === 0){ status.textContent = 'No coordinates found in file'; return }
        // POST drivers (use first as depot)
        drivers.push({id: 'drv-csv-1', lat: trips[0].lat, lon: trips[0].lon, label: 'CSV depot', active: true});
        const respD = await fetch('/api/drivers', {method:'POST', headers:{'Content-Type':'application/json','X-API-Token': token}, body: JSON.stringify({drivers})});
        const rd = await respD.json();
        if(!respD.ok) throw new Error('drivers upload failed: '+ JSON.stringify(rd));
        const respT = await fetch('/api/trips', {method:'POST', headers:{'Content-Type':'application/json','X-API-Token': token}, body: JSON.stringify({trips})});
        const rt = await respT.json();
        if(!respT.ok) throw new Error('trips upload failed: '+ JSON.stringify(rt));
        status.textContent = `Imported ${trips.length} trips`; 
        // refresh preview
        await loadRoutes();
    }catch(err){ status.textContent = 'Import error: ' + err }
});

// CSV import handler: parse simple CSV/TSV client-side and POST to API
document.getElementById('csvFileInput').addEventListener('change', async (ev) => {
    const f = ev.target.files[0];
    const mappingEl = document.getElementById('csvMapping');
    const detected = document.getElementById('detectedCols');
    const selLat = document.getElementById('mapLat');
    const selLon = document.getElementById('mapLon');
    const selLabel = document.getElementById('mapLabel');
    mappingEl.style.display = 'none';
    detected.textContent = '';
    selLat.innerHTML = '<option value="">(auto)</option>';
    selLon.innerHTML = '<option value="">(auto)</option>';
    selLabel.innerHTML = '<option value="">(auto)</option>';
    if(!f) return;
    const text = await f.text();
    const lines = text.split(/\r?\n/).map(s=>s.trim()).filter(Boolean);
    if(lines.length === 0) return;
    // detect delimiter
    const sample = lines.slice(0,5).join('\n');
    const delim = sample.indexOf('\t') !== -1 ? '\t' : (sample.indexOf(',') !== -1 ? ',' : null);
    const cols = delim ? lines[0].split(delim).map(c=>c.trim()) : (lines[0].split(/\s+/).map(c=>c.trim()));
    if(cols.length > 1){
        mappingEl.style.display = 'block';
        detected.textContent = cols.join(', ');
        cols.forEach((c,i)=>{
            const opt1 = document.createElement('option'); opt1.value = i; opt1.text = `${i}: ${c}`;
            const opt2 = document.createElement('option'); opt2.value = c; opt2.text = `${c}`;
            selLat.appendChild(opt1.cloneNode(true)); selLat.appendChild(opt2.cloneNode(true));
            selLon.appendChild(opt1.cloneNode(true)); selLon.appendChild(opt2.cloneNode(true));
            selLabel.appendChild(opt1.cloneNode(true)); selLabel.appendChild(opt2.cloneNode(true));
        });
    }
});

// Live polling: poll /api/live_status and show drivers/trips on preview map
let liveInterval = null;
function drawLiveSnapshot(payload){
    try{
        const map = ensurePreviewMap();
        clearPreviewMap();
        const drivers = payload.drivers || [];
        const trips = payload.trips || [];
        // draw trips as small grey markers
        trips.forEach((t,i)=>{
            try{
                const m = L.circleMarker([t.lat, t.lon], {radius:6, color:'#666', fillOpacity:0.9}).bindPopup(`Trip: ${t.id || ''}<br>${t.label || ''}`);
                previewLayerGroup.addLayer(m);
            }catch(e){}
        });
        // draw drivers as numbered colored markers
        drivers.forEach((d,i)=>{
            try{
                const icon = L.divIcon({className:'num-icon', html:`<div style="background:${colors[i % colors.length]};color:#fff;border-radius:12px;padding:2px 6px;font-weight:bold">${d.id || i+1}</div>`, iconSize:[28,28]});
                const m = L.marker([d.lat, d.lon], {icon}).bindPopup(`Driver: ${d.id}<br>Active: ${d.active ? 'yes' : 'no'}`);
                previewLayerGroup.addLayer(m);
            }catch(e){}
        });
        if(trips.length && previewLayerGroup.getLayers().length){ try{ previewMap.fitBounds(previewLayerGroup.getBounds().pad(0.08)); }catch(e){} }
    }catch(e){ console.warn('drawLiveSnapshot failed', e) }
}

async function pollLiveOnce(){
    try{
        const resp = await fetch('/api/live_status');
        if(!resp.ok) return;
        const data = await resp.json();
        const liveStatus = document.getElementById('liveStatus');
        if(data && data.ok){ liveStatus.textContent = `Live: ${ (data.drivers||[]).length } drivers, ${ (data.trips||[]).length } trips`; drawLiveSnapshot(data); }
    }catch(e){ console.warn('live poll error', e); }
}

document.getElementById('liveToggle').addEventListener('change', (ev)=>{
    const checked = ev.target.checked;
    const liveStatus = document.getElementById('liveStatus');
    if(checked){
        liveStatus.textContent = 'Live: polling...';
        pollLiveOnce();
        liveInterval = setInterval(pollLiveOnce, 5000);
    } else {
        liveStatus.textContent = 'Live: off';
        if(liveInterval){ clearInterval(liveInterval); liveInterval = null; }
        clearPreviewMap();
    }
});
</script>

</body>
</html>
"""

@app.route('/')
def index():
    csvs = [f for f in os.listdir('.') if f.startswith('route_vehicle_') and f.endswith('.csv')]
    return render_template_string(INDEX_HTML, csvs=csvs)

@app.route('/map')
def map_view():
    if not os.path.exists('routes_map.html'):
        return 'routes_map.html not found', 404
    return send_from_directory('.', 'routes_map.html')

@app.route('/routes.json')
def routes_json():
    if not os.path.exists('routes.json'):
        return jsonify({'error': 'routes.json not found'}), 404
    with open('routes.json') as f:
        return jsonify(json.load(f))

@app.route('/debug')
def debug_view():
    if os.path.exists('debug/clusters_debug.json'):
        return send_from_directory('debug', 'clusters_debug.json')
    if os.path.exists('clusters_debug_manual.json'):
        return send_from_directory('.', 'clusters_debug_manual.json')
    return 'No cluster debug available', 404

@app.route('/download/<path:filename>')
def download(filename):
    if os.path.exists(filename):
        return send_from_directory('.', filename, as_attachment=True)
    return abort(404)

if __name__ == '__main__':
    # bind to all interfaces for convenience in container or remote uses; adjust as needed
    app.run(host='0.0.0.0', port=5000, debug=False)
