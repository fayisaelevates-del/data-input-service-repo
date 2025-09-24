"""Regenerate enriched routes.json using the current routes.json stop indices and vrp_prototype.save_outputs.
This script is safe to run repeatedly and will overwrite routes.json with the enriched format (per-stop eta_hhmm and depart_hhmm).
"""
import json
import os
# ruff: noqa: E402

proj_root = os.path.dirname(__file__)
if proj_root:
    os.chdir(proj_root)

# ensure we import the project's module
import vrp_prototype

# load existing routes.json produced earlier (vehicle -> stops list)
with open('routes.json') as f:
    data = json.load(f)

# convert to routes list of lists of ints (route sequences)
routes = []
for item in data:
    # item may be {'vehicle': N, 'stops': [..]} or enriched already
    stops = item.get('stops')
    if stops and isinstance(stops, list) and stops and isinstance(stops[0], dict):
        # already enriched: extract stop indices in sequence order
        seq = [0]
        seq += [s['stop'] for s in stops]
        seq.append(0)
        routes.append(seq)
    else:
        routes.append([int(s) for s in stops])

# determine stops coordinates
# prefer input.json if present
stops_coords = None
if os.path.exists('input.json'):
    with open('input.json') as f:
        d = json.load(f)
    if d.get('stops'):
        stops_coords = [tuple(s) for s in d['stops']]

if stops_coords is None:
    # fallback to vrp_prototype.STOPS
    stops_coords = vrp_prototype.STOPS

# build time matrix
tm = vrp_prototype.build_time_matrix(stops_coords)

# call save_outputs to rewrite routes.json in enriched format
vrp_prototype.save_outputs(routes, stops_coords, tm)
print('Rewrote routes.json with enriched per-stop fields')
