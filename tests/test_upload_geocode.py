import io
import sqlite3
import importlib
import sys


def _import_app_with_tmp_db(tmp_path, monkeypatch):
    # Ensure ROUTES_DB_PATH is set before importing serve_routes so DB_PATH binds correctly
    db_path = str(tmp_path / 'test_data.db')
    monkeypatch.setenv('ROUTES_DB_PATH', db_path)
    # Remove cached module so it picks up the new env var
    if 'serve_routes' in sys.modules:
        del sys.modules['serve_routes']
    serve_routes = importlib.import_module('serve_routes')
    # initialize DB in that module
    try:
        serve_routes.init_db()
    except Exception:
        pass
    return serve_routes.app, db_path


def test_upload_geocode_form_flag(tmp_path, monkeypatch):
    app, db_path = _import_app_with_tmp_db(tmp_path, monkeypatch)
    client = app.test_client()
    # prepare an address-only CSV
    data = b"address\n1 Infinite Loop, Cupertino, CA\n"
    rv = client.post('/api/upload_csv', data={'file': (io.BytesIO(data), 'addr.csv'), 'geocode': '1'}, headers={'X-API-Token': 'testing'}, content_type='multipart/form-data')
    assert rv.status_code == 200, rv.data
    j = rv.get_json()
    assert j.get('ok') is True
    assert j.get('inserted', 0) >= 1
    # check DB cache/trips
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM trips")
    tcount = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM geocode_cache")
    gcount = cur.fetchone()[0]
    conn.close()
    assert tcount >= 1
    assert gcount >= 1


def test_upload_geocode_query_flag(tmp_path, monkeypatch):
    app, db_path = _import_app_with_tmp_db(tmp_path, monkeypatch)
    client = app.test_client()
    data = b"address\n1600 Amphitheatre Parkway, Mountain View, CA\n"
    rv = client.post('/api/upload_csv?geocode=1', data={'file': (io.BytesIO(data), 'addr2.csv')}, headers={'X-API-Token': 'testing'}, content_type='multipart/form-data')
    assert rv.status_code == 200, rv.data
    j = rv.get_json()
    assert j.get('ok') is True
    assert j.get('inserted', 0) >= 1
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM trips")
    tcount = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM geocode_cache")
    gcount = cur.fetchone()[0]
    conn.close()
    assert tcount >= 1
    assert gcount >= 1
