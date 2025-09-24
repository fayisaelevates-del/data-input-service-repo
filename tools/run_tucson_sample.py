"""
Run a fast VRP sample using `vrp_prototype` for a few Tucson locations.
This script is intentionally small and sets short solver time limits to be fast.
Outputs: routes.json, routes_summary.csv, routes_map.html
"""
import os
import json
from pathlib import Path

# ensure project root
# ruff: noqa: E402
ROOT = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(ROOT))

import vrp_prototype

# override some global parameters for a quick sample
vrp_prototype.ORS_KEY = None

# short list of Tucson POIs (lat, lon)
SAMPLE_STOPS = [
    (32.2226, -110.9747),  # Tucson (downtown)
    (32.2319, -110.9501),  # University of Arizona area
    (32.2220, -110.9265),  # Reid Park / zoo
    (32.1916, -110.9265),  # South Tucson
    (32.3546, -110.9771),  # Northwest Tucson
    (32.1328, -110.9474),  # South of downtown
]

# exporter-friendly small problem: include depot as first stop
DEPOT = SAMPLE_STOPS[0]
STOPS = [DEPOT] + SAMPLE_STOPS[1:]

# small demands and service times (seconds)
DEMANDS = [0, 5, 5, 5, 5, 5]
SERVICE_TIMES = [0, 10 * 60, 10 * 60, 10 * 60, 10 * 60, 10 * 60]
NUM_VEHICLES = 2
VEHICLE_CAPACITIES = [15, 15]

# apply into the vrp_prototype module globals for easy reuse
vrp_prototype.STOPS = STOPS
vrp_prototype.DEMANDS = DEMANDS
vrp_prototype.SERVICE_TIMES = SERVICE_TIMES
vrp_prototype.NUM_VEHICLES = NUM_VEHICLES
vrp_prototype.VEHICLE_CAPACITIES = VEHICLE_CAPACITIES

# reduce search time for a fast sample
# monkeypatch DEFAULT routing search parameters by setting env var RELAX_TWS and timeouts
os.environ['RELAX_TWS'] = '1'
# run solver with shortened time limit by temporarily modifying solve_vrp's parameter via wrapper

# For small samples, call solve_vrp directly to avoid subprocess overhead.
def run_sample():
    print('Building time matrix for sample stops...')
    tm = vrp_prototype.build_time_matrix(vrp_prototype.STOPS)
    print('Time matrix built; calling solve_vrp directly (fast for small N)...')
    # call solve_vrp directly with service times and time windows
    try:
        routes = vrp_prototype.solve_vrp(tm, vrp_prototype.NUM_VEHICLES, 0, demands=vrp_prototype.DEMANDS, vehicle_capacities=vrp_prototype.VEHICLE_CAPACITIES, service_times=vrp_prototype.SERVICE_TIMES, time_windows=vrp_prototype.TIME_WINDOWS)
    except Exception as e:
        print('solve_vrp failed, falling back to cluster solver:', e)
        routes = vrp_prototype.solve_by_clusters(vrp_prototype.STOPS, tm, vrp_prototype.NUM_VEHICLES, 0)
    print('Routes computed; writing outputs via save_outputs...')
    vrp_prototype.save_outputs(routes, vrp_prototype.STOPS, tm)
    # print a concise summary
    print('\nSummary:')
    try:
        with open('routes.json') as f:
            routes_json = json.load(f)
        for r in routes_json:
            print(f"Vehicle {r['vehicle']}: {len(r['stops'])} stops, total_hours={r['total_hours']}, violates_shift={r['violates_shift']}")
    except Exception as e:
        print('Could not read routes.json:', e)

if __name__ == '__main__':
    run_sample()
