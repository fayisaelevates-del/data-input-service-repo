"""
Greedy VRP solver (no OR-Tools required).
- Very small dependency set: only `folium` for map output.
- Assigns stops to vehicles by nearest-neighbor starting from depot.
- Produces `routes_greedy.json` and `routes_greedy_map.html`.
"""

import json
import math
from typing import List, Tuple

try:
    import folium
except Exception:
    raise SystemExit('Please install folium (pip install folium)')

STOPS: List[Tuple[float, float]] = [
    (32.257254, -110.9723225),
    (32.1162014, -111.0419424),
    (32.4078759, -111.0204164),
    (32.2753731, -110.9443301),
    (32.1495514, -111.0237159),
    (32.5109786, -110.9222564),
    (32.2723617, -110.9674986),
    (32.3451874, -110.9872146),
]

NUM_VEHICLES = 2
DEPOT = 0


def haversine(a, b):
    lat1, lon1 = a
    lat2, lon2 = b
    R = 6371  # km
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    x = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.asin(math.sqrt(x))


def greedy_solve(stops, num_vehicles, depot=0):
    unassigned = set(range(len(stops)))
    unassigned.remove(depot)
    routes = [[depot] for _ in range(num_vehicles)]

    # Initialize vehicle positions at depot
    positions = [depot for _ in range(num_vehicles)]

    while unassigned:
        progress = False
        for v in range(num_vehicles):
            if not unassigned:
                break
            cur = positions[v]
            # find nearest unassigned
            nearest = None
            nearest_d = float('inf')
            for u in unassigned:
                d = haversine(stops[cur], stops[u])
                if d < nearest_d:
                    nearest = u
                    nearest_d = d
            if nearest is None:
                continue
            routes[v].append(nearest)
            positions[v] = nearest
            unassigned.remove(nearest)
            progress = True
        if not progress:
            break
    # optionally return to depot
    for v in range(num_vehicles):
        if routes[v][-1] != depot:
            routes[v].append(depot)
    return routes


def save_outputs(routes, stops):
    out = []
    for vid, route in enumerate(routes, start=1):
        out.append({'vehicle': vid, 'stops': route})
    with open('routes_greedy.json', 'w') as f:
        json.dump(out, f, indent=2)

    m = folium.Map(location=stops[0], zoom_start=11)
    colors = ['red', 'blue', 'green', 'purple', 'orange']
    for vid, route in enumerate(routes):
        coords = [stops[i] for i in route]
        folium.PolyLine(coords, color=colors[vid % len(colors)], weight=4, opacity=0.7).add_to(m)
        for idx, s in enumerate(route):
            folium.CircleMarker(location=stops[s], radius=4, color=colors[vid % len(colors)], fill=True).add_to(m)
    m.save('routes_greedy_map.html')
    print('Saved routes_greedy.json and routes_greedy_map.html')


def main():
    routes = greedy_solve(STOPS, NUM_VEHICLES, DEPOT)
    save_outputs(routes, STOPS)


if __name__ == '__main__':
    main()
