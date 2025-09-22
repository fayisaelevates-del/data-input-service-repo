import io
import os
import sqlite3
import importlib
import importlib.util
import sys


def _import_app_with_tmp_db(tmp_path, monkeypatch):
    db_path = str(tmp_path / 'test_data.db')
    monkeypatch.setenv('ROUTES_DB_PATH', db_path)
    if 'serve_routes' in sys.modules:
        del sys.modules['serve_routes']
    try:
        serve_routes = importlib.import_module('serve_routes')
    except ModuleNotFoundError:
        # Fallback: load the module directly from the project file path.
        here = os.path.dirname(__file__)
        project_root = os.path.abspath(os.path.join(here, '..'))
        module_path = os.path.join(project_root, 'serve_routes.py')
        spec = importlib.util.spec_from_file_location('serve_routes', module_path)
        serve_routes = importlib.util.module_from_spec(spec)
        sys.modules['serve_routes'] = serve_routes
        spec.loader.exec_module(serve_routes)
    try:
        serve_routes.init_db()
    except Exception:
        pass
    return serve_routes, serve_routes.app, db_path


def test_upload_geocode_mocked(tmp_path, monkeypatch):
    # monkeypatch the geocoder to avoid network calls
    serve_routes, app, db_path = _import_app_with_tmp_db(tmp_path, monkeypatch)

    def fake_geocode(q):
        # return a simple deterministic lat/lon for any query and write to cache
        lat, lon = (12.345678, 98.765432)
        try:
            import sqlite3
            import time
            key = (q or '').strip().lower()
            with sqlite3.connect(serve_routes.DB_PATH) as conn:
                cur = conn.cursor()
                cur.execute('REPLACE INTO geocode_cache (query, lat, lon, fetched_at) VALUES (?, ?, ?, ?)', (key, lat, lon, time.time()))
                conn.commit()
        except Exception:
            pass
        return (lat, lon)

    monkeypatch.setattr(serve_routes, '_geocode_query', fake_geocode)

    client = app.test_client()
    data = b"address\nSomewhere, Earth\n"
    rv = client.post('/api/upload_csv?geocode=1', data={'file': (io.BytesIO(data), 'addr.csv')}, headers={'X-API-Token': 'testing'}, content_type='multipart/form-data')
    assert rv.status_code == 200, rv.data
    j = rv.get_json()
    assert j.get('ok') is True
    assert j.get('geocoded') is True
    # check DB entries
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM trips")
    tcount = cur.fetchone()[0]
    cur.execute("SELECT lat, lon FROM geocode_cache LIMIT 1")
    row = cur.fetchone()
    conn.close()
    assert tcount >= 1
    assert row is not None
    assert abs(row[0] - 12.345678) < 1e-6
    assert abs(row[1] - 98.765432) < 1e-6
