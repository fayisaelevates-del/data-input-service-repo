"""
Simple matrix cache + safe OpenRouteService matrix client.

Design choices / assumptions:
- Use an on-disk sqlite3 cache keyed by a sha256 of the rounded coordinate list.
- For safety and cost control, when the number of locations > ORS_MAX_LOCATIONS we avoid sending a full ORS matrix
  request and fall back to haversine. This keeps costs bounded when users provide large problems.
- ORS behaviour: this client issues a single matrix request for the full coordinate list when small
  (n <= ORS_MAX_LOCATIONS) and caches the resulting durations (in seconds) as JSON.
- TTL (seconds) controls how long cached entries are considered fresh. Default: 7 days.

This is intentionally small and dependency-free (uses stdlib sqlite3, json, hashlib).
"""

import os
import sqlite3
import json
import time
import hashlib
from typing import List, Tuple, Optional

DB_PATH = os.environ.get('MATRIX_CACHE_DB', 'matrix_cache.db')
TTL_SECONDS = int(os.environ.get('MATRIX_CACHE_TTL', 7 * 24 * 3600))
ORS_KEY = os.environ.get('ORS_API_KEY')
ORS_URL = 'https://api.openrouteservice.org/v2/matrix/driving-car'
# Practical limit for single ORS matrix request to avoid huge API calls. Adjust if you have higher quota.
ORS_MAX_LOCATIONS = int(os.environ.get('ORS_MAX_LOCATIONS', 50))

# Simple runtime metrics exposed for smoke tests / instrumentation
METRICS = {
    'ors_calls': 0,
    'ors_failures': 0,
    'cache_hits': 0,
}


def _make_key(coords: List[Tuple[float, float]]) -> str:
    # round coordinates to 6 decimals to normalize tiny differences
    s = '|'.join(f"{round(lat,6)},{round(lon,6)}" for lat, lon in coords)
    return hashlib.sha256(s.encode('utf-8')).hexdigest()


def _ensure_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('''CREATE TABLE IF NOT EXISTS matrices (
        key TEXT PRIMARY KEY,
        ts INTEGER,
        coords TEXT,
        matrix TEXT
    )''')
    conn.commit()
    return conn


def get_cached_matrix(coords: List[Tuple[float, float]]) -> Optional[List[List[int]]]:
    key = _make_key(coords)
    conn = _ensure_db()
    cur = conn.cursor()
    cur.execute('SELECT ts, matrix FROM matrices WHERE key = ?', (key,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    ts, matrix_json = row
    if int(time.time()) - ts > TTL_SECONDS:
        return None
    try:
        METRICS['cache_hits'] += 1
    except Exception:
        pass
    return json.loads(matrix_json)


def set_cached_matrix(coords: List[Tuple[float, float]], matrix: List[List[int]]):
    key = _make_key(coords)
    conn = _ensure_db()
    cur = conn.cursor()
    cur.execute('REPLACE INTO matrices (key, ts, coords, matrix) VALUES (?, ?, ?, ?)',
                (key, int(time.time()), json.dumps(coords), json.dumps(matrix)))
    conn.commit()
    conn.close()


def haversine(a: Tuple[float, float], b: Tuple[float, float]) -> float:
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


def build_haversine_matrix(coords: List[Tuple[float, float]]) -> List[List[int]]:
    n = len(coords)
    m = [[0] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            if i == j:
                m[i][j] = 0
            else:
                km = haversine(coords[i], coords[j])
                hours = km / 50.0
                m[i][j] = int(hours * 3600)
    return m


def fetch_matrix_from_ors(coords: List[Tuple[float, float]]) -> List[List[int]]:
    """Fetch a full duration matrix from ORS. Caller must ensure len(coords) <= ORS_MAX_LOCATIONS.
    Returns matrix in seconds.
    """
    import requests
    coords_payload = [[lon, lat] for lat, lon in coords]
    body = {"locations": coords_payload, "metrics": ["duration"], "units": "km"}
    headers = {"Authorization": ORS_KEY, "Content-Type": "application/json"}
    try:
        METRICS['ors_calls'] += 1
    except Exception:
        pass
    resp = requests.post(ORS_URL, json=body, headers=headers, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    durations = data.get('durations')
    if not durations:
        try:
            METRICS['ors_failures'] += 1
        except Exception:
            pass
        raise RuntimeError('ORS returned no durations')
    n = len(coords)
    mat = [[int(durations[i][j]) for j in range(n)] for i in range(n)]
    return mat


def get_time_matrix(coords: List[Tuple[float, float]]) -> List[List[int]]:
    """Return a square time matrix (seconds) for the provided coords.

    Behaviour:
    - If a fresh cached matrix is available, return it.
    - If an ORS key is present and len(coords) <= ORS_MAX_LOCATIONS, request ORS then cache the result.
    - Otherwise, compute haversine fallback and cache it.
    """
    # quick return for trivial
    if len(coords) <= 1:
        return [[0] * len(coords) for _ in range(len(coords))]
    cached = get_cached_matrix(coords)
    if cached is not None:
        return cached
    # try ORS if available and problem small
    if ORS_KEY and len(coords) <= ORS_MAX_LOCATIONS:
        try:
            mat = fetch_matrix_from_ors(coords)
            set_cached_matrix(coords, mat)
            return mat
        except Exception:
            # fall back to haversine on any ORS failure
            try:
                METRICS['ors_failures'] += 1
            except Exception:
                pass
    mat = build_haversine_matrix(coords)
    try:
        set_cached_matrix(coords, mat)
    except Exception:
        # ignore cache errors
        pass
    return mat
