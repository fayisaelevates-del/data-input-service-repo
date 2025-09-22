import os
import json
import math
import tempfile

# Read input.json (user-edited)
with open('input.json') as f:
    data = json.load(f)

stops = [tuple(s) for s in data.get('stops', [])]
demands = data.get('demands', [])
if not stops:
    raise SystemExit('No stops in input.json')

# env knobs
CLUSTER_TARGET_SIZE = os.environ.get('CLUSTER_TARGET_SIZE')
if CLUSTER_TARGET_SIZE is not None:
    try:
        CLUSTER_TARGET_SIZE = int(CLUSTER_TARGET_SIZE)
    except Exception:
        CLUSTER_TARGET_SIZE = None

# simple sweep partition (copy of vrp_prototype.sweep_partition)

def sweep_partition(stops, k, demands):
    if k <= 1:
        return [list(range(1, len(stops)))]
    depot = stops[0]
    pts = [(i, stops[i]) for i in range(1, len(stops))]
    def angle(p):
        lat, lon = p[1]
        dlat = lat - depot[0]
        dlon = lon - depot[1]
        return math.atan2(dlat, dlon)
    pts_sorted = sorted(pts, key=angle)
    total_demand = sum(demands[1:]) if len(demands) >= len(stops) else sum(demands[1:])
    target = total_demand / k if k>0 else total_demand
    clusters = []
    current = []
    cum = 0
    for idx, _ in pts_sorted:
        current.append(idx)
        d = int(demands[idx]) if idx < len(demands) else 1
        cum += d
        if cum >= target and len(clusters) < k - 1:
            clusters.append(current)
            current = []
            cum = 0
    clusters.append(current)
    while len(clusters) < k:
        clusters.append([])
    return clusters

# compute k
num_stops = len(stops)
num_vehicles = int(data.get('num_vehicles', max(1, num_stops//5)))
k = num_vehicles
if CLUSTER_TARGET_SIZE and CLUSTER_TARGET_SIZE>0:
    k = max(1, math.ceil((len(stops)-1)/float(CLUSTER_TARGET_SIZE)))

clusters = sweep_partition(stops, k, demands)
# build info
cluster_info = []
for c in clusters:
    total_d = sum(int(demands[i]) if i < len(demands) else 1 for i in c)
    cluster_info.append({'size': len(c), 'demand': int(total_d), 'indices': [int(i) for i in c]})

payload = {'k': int(k), 'clusters': cluster_info}
# atomic write into debug dir (best-effort) and also write a manual copy in repo root
try:
    os.makedirs('debug', exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='clusters_debug_', suffix='.json', dir='debug')
    try:
        with os.fdopen(fd, 'w') as fh:
            json.dump(payload, fh, indent=2)
        os.replace(tmp, os.path.join('debug', 'clusters_debug.json'))
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except Exception:
                pass
    print('Wrote debug/clusters_debug.json')
except Exception as e:
    print('Failed to write debug file:', e)

# always write a manual debug file in repo root so we can inspect it regardless
try:
    with open('clusters_debug_manual.json', 'w') as mf:
        json.dump(payload, mf, indent=2)
    print('Wrote clusters_debug_manual.json')
except Exception as e:
    print('Failed to write clusters_debug_manual.json:', e)

print('PAYLOAD:', json.dumps(payload))
