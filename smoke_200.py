import json
import random
import time
import os
from pathlib import Path

ROOT = Path(__file__).parent

def make_stops(n=200, center=(32.257254, -110.9723225), spread_km=20):
    lat0, lon0 = center
    stops = [center]
    for i in range(n):
        # random small offset in degrees (~111 km per degree lat)
        dlat = (random.random() - 0.5) * (spread_km / 111)
        dlon = (random.random() - 0.5) * (spread_km / (111 * abs(math.cos(math.radians(lat0))) + 1e-6))
        stops.append((lat0 + dlat, lon0 + dlon))
    return stops


def write_input(stops):
    data = {
        'stops': stops,
        'demands': [0] + [1] * (len(stops) - 1),
        'num_vehicles': 50
    }
    with open(ROOT / 'input.json', 'w') as f:
        json.dump(data, f)


def run_test():
    import subprocess
    import sys
    # ensure ORS key is unset to force haversine fallback for cost control
    env = os.environ.copy()
    env.pop('ORS_API_KEY', None)
    # relax time windows for large synthetic tests
    env['RELAX_TWS'] = '1'
    t0 = time.time()
    proc = subprocess.run([sys.executable, str(ROOT / 'vrp_prototype.py')], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    t1 = time.time()
    print('Return code', proc.returncode)
    print('Elapsed seconds', t1 - t0)
    print(proc.stdout.decode('utf-8')[:2000])
    if proc.returncode != 0:
        print('ERR:', proc.stderr.decode('utf-8')[:2000])


if __name__ == '__main__':
    import math
    stops = make_stops(200)
    write_input(stops)
    run_test()
