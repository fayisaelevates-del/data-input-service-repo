import os
import json
import math

with open('input.json') as f:
    data = json.load(f)

stops = [tuple(s) for s in data.get('stops', [])]
demands = data.get('demands', [])
num_vehicles = int(data.get('num_vehicles', max(1, len(stops)//5)))

cls_target = os.environ.get('CLUSTER_TARGET_SIZE')
if cls_target is not None:
    try:
        cls_target = int(cls_target)
    except Exception:
        cls_target = None

k = num_vehicles
if cls_target and cls_target > 0:
    k = max(1, math.ceil((len(stops)-1)/float(cls_target)))

# sweep
if k <= 1:
    clusters = [list(range(1, len(stops)))]
else:
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

payload = {'k': int(k), 'clusters': [{'size': len(c), 'demand': sum(int(demands[i]) if i < len(demands) else 1 for i in c), 'indices': [int(i) for i in c]} for c in clusters]}

with open('clusters_debug_manual.json', 'w') as mf:
    json.dump(payload, mf, indent=2)

print('Wrote clusters_debug_manual.json')
