import importlib
import sys


def _import_app_with_tmp_db(tmp_path, monkeypatch):
    db_path = str(tmp_path / 'test_prefs.db')
    monkeypatch.setenv('ROUTES_DB_PATH', db_path)
    if 'serve_routes' in sys.modules:
        del sys.modules['serve_routes']
    serve_routes = importlib.import_module('serve_routes')
    try:
        serve_routes.init_db()
    except Exception:
        pass
    return serve_routes.app, db_path


def test_mapping_pref_crud(tmp_path, monkeypatch):
    app, db = _import_app_with_tmp_db(tmp_path, monkeypatch)
    client = app.test_client()
    # get without id
    rv = client.get('/api/mapping_pref')
    assert rv.status_code == 400
    # set mapping (needs token)
    payload = {'id': 'user-1', 'pref': {'lat': 0, 'lon': 1}}
    rv = client.post('/api/mapping_pref', json=payload, headers={'X-API-Token': 'testing'})
    assert rv.status_code == 200
    j = rv.get_json()
    assert j.get('ok')
    # retrieve
    rv2 = client.get('/api/mapping_pref?id=user-1')
    assert rv2.status_code == 200
    j2 = rv2.get_json()
    assert j2.get('pref') == {'lat': 0, 'lon': 1}
