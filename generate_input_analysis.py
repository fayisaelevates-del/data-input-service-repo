"""Generate analysis and enriched input files from input.json
- analysis_input.json: summary statistics useful for tuning
- input_enriched.json: same stops/demands plus default service_times, time_windows, vehicle_capacities
"""
import json
import os
import math

p = os.path.join(os.path.dirname(__file__), 'input.json')
with open(p) as f:
    data = json.load(f)
stops = data.get('stops', [])
demands = data.get('demands', [])
num_vehicles = int(data.get('num_vehicles', max(1, len(stops)//5)))

# defaults
DEFAULT_SERVICE_SEC = 600  # 10 minutes per stop
SERVICE_TIMES = [0] + [DEFAULT_SERVICE_SEC] * (len(stops)-1)
# allow caller to specify an extra wait before recording a 'no-load'
# e.g. input.json may include "wait_before_no_load": 600 (seconds)
WAIT_BEFORE_NO_LOAD = int(data.get('wait_before_no_load', 0))
# default time windows: full shift 05:00-17:00
SHIFT_START = 5*3600
SHIFT_END = 17*3600
TIME_WINDOWS = [(SHIFT_START, SHIFT_END) for _ in range(len(stops))]

# vehicle capacities: choose value so average load <= capacity
total_demand = sum(demands) if demands else 0
avg_load = (total_demand / num_vehicles) if num_vehicles else total_demand
# set capacity to ceil(avg_load * 1.5) with minimum 10
cap = max(10, math.ceil(avg_load * 1.5))
VEHICLE_CAPACITIES = [cap] * num_vehicles

analysis = {
    'stops_count': len(stops),
    'demands_count': len(demands),
    'num_vehicles': num_vehicles,
    'total_demand': total_demand,
    'avg_load_per_vehicle': avg_load,
    'suggested_vehicle_capacity': cap,
    'service_time_sec_default': DEFAULT_SERVICE_SEC,
    'time_window_default': [SHIFT_START, SHIFT_END]
}

# write analysis file
with open(os.path.join(os.path.dirname(__file__), 'analysis_input.json'), 'w') as af:
    json.dump(analysis, af, indent=2)

# build enriched input
enriched = dict(data)  # shallow copy
if 'service_times' in enriched:
    # merge: add WAIT_BEFORE_NO_LOAD to each non-depot service time
    sts = list(enriched['service_times'])
    # ensure list length matches stops
    if len(sts) < len(stops):
        sts = sts + [DEFAULT_SERVICE_SEC] * (len(stops) - len(sts))
    # add wait_before_no_load to non-depot entries
    if WAIT_BEFORE_NO_LOAD:
        sts = [sts[0]] + [s + WAIT_BEFORE_NO_LOAD for s in sts[1:]]
    enriched['service_times'] = sts
else:
    # build default service times and include wait_before_no_load
    base = SERVICE_TIMES
    if WAIT_BEFORE_NO_LOAD:
        base = [base[0]] + [s + WAIT_BEFORE_NO_LOAD for s in base[1:]]
    enriched['service_times'] = base
if 'time_windows' not in enriched:
    enriched['time_windows'] = TIME_WINDOWS
if 'vehicle_capacities' not in enriched:
    enriched['vehicle_capacities'] = VEHICLE_CAPACITIES
# ensure num_vehicles present
enriched['num_vehicles'] = num_vehicles

with open(os.path.join(os.path.dirname(__file__), 'input_enriched.json'), 'w') as ef:
    json.dump(enriched, ef, indent=2)

print('Wrote analysis_input.json and input_enriched.json')
