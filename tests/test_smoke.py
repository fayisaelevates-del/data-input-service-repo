import importlib
from pathlib import Path


def test_smoke_import_and_init_db(tmp_path, monkeypatch):
    """Basic smoke: module imports, init_db creates sqlite file at configured path.

    We redirect ROUTES_DB_PATH into a temp directory so the real workspace
    isn't modified during CI.
    """
    db_path = tmp_path / "smoke.db"
    monkeypatch.setenv("ROUTES_DB_PATH", str(db_path))

    mod = importlib.import_module("serve_routes")

    # init_db should create the file without raising
    mod.init_db()
    assert db_path.exists(), "Database file should be created by init_db()"

    # Optional: ensure helper functions are present
    assert hasattr(mod, "parse_csv_to_trips")
