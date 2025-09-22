import json
import os

with open('input.json') as f:
    data = json.load(f)

stops = data.get('stops', [])
demands = data.get('demands', [])
num_vehicles = int(data.get('num_vehicles', max(1, len(stops)//5)))

n = len(stops)
indices = list(range(1, n))  # exclude depot
k = num_vehicles
if k <= 0:
    k = 1

# even chunking
clusters = []
base = len(indices) // k
rem = len(indices) % k
it = iter(indices)
for i in range(k):
    size = base + (1 if i < rem else 0)
    c = []
    for _ in range(size):
        try:
            c.append(next(it))
        except StopIteration:
            break
    clusters.append(c)

cluster_info = []
for c in clusters:
    total_d = sum(int(demands[i]) if i < len(demands) else 1 for i in c)
    cluster_info.append({'size': int(len(c)), 'demand': int(total_d), 'indices': [int(i) for i in c]})

payload = {'k': int(k), 'clusters': cluster_info}

os.makedirs('debug', exist_ok=True)
with open(os.path.join('debug', 'clusters_debug.json'), 'w') as fh:
    json.dump(payload, fh, indent=2)
with open('clusters_debug_manual.json', 'w') as mf:
    json.dump(payload, mf, indent=2)

print('Wrote debug/clusters_debug.json and clusters_debug_manual.json with k=', k)
