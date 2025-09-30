"""
Minimal VRP prototype using OR-Tools.
- If you provide an OpenRouteService API key via the ORS_API_KEY environment variable, the script will request travel durations from ORS.
- Otherwise it will fall back to great-circle (haversine) travel times (approximate) so you can run locally without external services.

Outputs:
- routes.json with per-vehicle stop order and estimated durations
- routes_map.html visualizing routes (folium)

This is intentionally small and synchronous for easy testing.
"""

import os
# ruff: noqa: E402
import json
import math
from typing import List, Tuple
import warnings

# Suppress noisy DeprecationWarnings coming from SWIG-wrapped native types (seen when
# importing OR-Tools). These warnings reference builtin types like SwigPyPacked,
# SwigPyObject, swigvarlink lacking a __module__ attribute. They originate in
# the native extension and are harmless for our runtime; suppress them so test logs
# are cleaner. If OR-Tools or the SWIG wrappers are updated, we can remove this.
warnings.filterwarnings('ignore', message='builtin type SwigPyPacked has no __module__ attribute', category=DeprecationWarning)
warnings.filterwarnings('ignore', message='builtin type SwigPyObject has no __module__ attribute', category=DeprecationWarning)
warnings.filterwarnings('ignore', message='builtin type swigvarlink has no __module__ attribute', category=DeprecationWarning)

_ORTOOLS_AVAILABLE = True
try:
    from ortools.constraint_solver import pywrapcp, routing_enums_pb2
except Exception:  # pragma: no cover - optional heavy dependency
    _ORTOOLS_AVAILABLE = False
    pywrapcp = None  # type: ignore
    routing_enums_pb2 = None  # type: ignore

_FOLIUM_AVAILABLE = True
try:
    import folium  # type: ignore
except Exception:  # pragma: no cover - optional visual dependency
    _FOLIUM_AVAILABLE = False
    folium = None  # type: ignore

# Optional: openrouteservice
ORS_URL = 'https://api.openrouteservice.org/v2/matrix/driving-car'
ORS_KEY = os.environ.get('ORS_API_KEY')

# Sample coordinates (lat, lon)
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
# Example vehicle capacities and demands (units are abstract, adjust to your needs)
# Reduce vehicle capacities to encourage splitting load across vehicles
VEHICLE_CAPACITIES = [40, 40]
# per-stop demand (0 for depot)
DEMANDS = [0, 10, 15, 20, 5, 10, 10, 8]
# per-stop service time in seconds (default 10 minutes for each stop except depot)
SERVICE_TIMES = [0, 600, 600, 600, 600, 600, 600, 600]
# default time windows for each stop (start, end) in seconds from route start
# default: whole shift (0..8 hours)
# Drivers work from 05:00 to 17:00
SHIFT_START = 5 * 3600
SHIFT_END = 17 * 3600
SHIFT_SECONDS = SHIFT_END - SHIFT_START
TIME_WINDOWS = [(SHIFT_START, SHIFT_END) for _ in range(len(STOPS))]
# If many vehicles are requested, relax per-stop time windows to improve feasibility and speed
RELAX_TWS_THRESHOLD = int(os.environ.get('RELAX_TWS_THRESHOLD', 100))
# Partitioning tuning: allow override via environment or input.json
from typing import Optional

CLUSTER_TARGET_SIZE: Optional[int] = None
_cts = os.environ.get('CLUSTER_TARGET_SIZE')
if _cts is not None:
    try:
        CLUSTER_TARGET_SIZE = int(_cts)
    except Exception:
        CLUSTER_TARGET_SIZE = None
CLUSTER_MAX_DEMAND: Optional[int] = None
_cmd = os.environ.get('CLUSTER_MAX_DEMAND')
if _cmd is not None:
    try:
        CLUSTER_MAX_DEMAND = int(_cmd)
    except Exception:
        CLUSTER_MAX_DEMAND = None



def haversine(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    lat1, lon1 = a
    lat2, lon2 = b
    R = 6371  # km
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    x = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.asin(math.sqrt(x))


def build_time_matrix(stops: List[Tuple[float, float]]) -> List[List[int]]:
    """Build time matrix using matrix_cache.get_time_matrix if available, otherwise fall back to
    the local ORS request or haversine fallback.
    """
    try:
        from matrix_cache import get_time_matrix
        return get_time_matrix(stops)
    except Exception:
        # best-effort fallback to original behavior
        n = len(stops)
        matrix = [[0] * n for _ in range(n)]
        if ORS_KEY:
            import requests
            coords = [[lon, lat] for lat, lon in stops]
            body = {"locations": coords, "metrics": ["duration"], "units": "km"}
            headers = {"Authorization": ORS_KEY, "Content-Type": "application/json"}
            resp = requests.post(ORS_URL, json=body, headers=headers, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            durations = data.get('durations') or data.get('durations')
            if durations:
                for i in range(n):
                    for j in range(n):
                        # ORS returns seconds; convert to int seconds
                        matrix[i][j] = int(durations[i][j])
                return matrix
        # fallback: haversine distances converted to seconds assuming 50 km/h
        for i in range(n):
            for j in range(n):
                if i == j:
                    matrix[i][j] = 0
                else:
                    km = haversine(stops[i], stops[j])
                    hours = km / 50.0
                    matrix[i][j] = int(hours * 3600)
        return matrix


def sweep_partition(stops: List[Tuple[float, float]], k: int, demands: List[int]):
    """Partition stops using a sweep algorithm balanced by cumulative demand.
    Returns list of clusters where each cluster is a list of global stop indices.
    """
    if k <= 1:
        return [list(range(1, len(stops)))]
    depot = stops[0]
    pts = [(i, stops[i]) for i in range(1, len(stops))]
    # compute angle from depot
    def angle(p):
        lat, lon = p[1]
        dlat = lat - depot[0]
        dlon = lon - depot[1]
        return math.atan2(dlat, dlon)

    pts_sorted = sorted(pts, key=angle)
    total_demand = sum(demands[1:])
    target = total_demand / k
    clusters: List[List[int]] = []
    current: List[int] = []
    cum = 0
    for idx, _ in pts_sorted:
        current.append(idx)
        cum += demands[idx]
        if cum >= target and len(clusters) < k - 1:
            clusters.append(current)
            current = []
            cum = 0
    clusters.append(current)
    # ensure we have exactly k clusters
    while len(clusters) < k:
        clusters.append([])
    return clusters


def write_clusters_manual(clusters, k):
    """Always write clusters_debug_manual.json in repo root (atomic)."""
    try:
        import tempfile
        import os as _os
        payload = {'k': int(k), 'clusters': [{'size': int(len(c)), 'demand': int(sum(int(DEMANDS[i]) if i < len(DEMANDS) else 1 for i in c)), 'indices': [int(i) for i in c]} for c in clusters]}
        fd, tmp_path = tempfile.mkstemp(prefix='clusters_debug_manual_', suffix='.json', dir='.')
        try:
            with os.fdopen(fd, 'w') as fh:
                json.dump(payload, fh, indent=2)
            _os.replace(tmp_path, _os.path.join('.', 'clusters_debug_manual.json'))
        finally:
            try:
                if _os.path.exists(tmp_path):
                    _os.remove(tmp_path)
            except Exception:
                pass
        print(f'[DEBUG] wrote clusters_debug_manual.json with {len(clusters)} clusters')
    except Exception as e:
        print(f'[DEBUG] failed to write clusters_debug_manual.json: {e}')


def _solve_cluster_task(args):
    # helper for parallel worker: args = (cluster, stops, depot)
    cluster, stops, depot = args
    if not cluster:
        return [depot, depot]
    sub_stops = [stops[depot]] + [stops[i] for i in cluster]
    sub_tm = build_time_matrix(sub_stops)
    # build subproblem-specific demands/service_times/time_windows
    sub_demands = [0] + [DEMANDS[i] if i < len(DEMANDS) else 1 for i in cluster]
    sub_service_times = [0] + [SERVICE_TIMES[i] if i < len(SERVICE_TIMES) else 0 for i in cluster]
    sub_time_windows = [TIME_WINDOWS[depot]] + [TIME_WINDOWS[i] if i < len(TIME_WINDOWS) else TIME_WINDOWS[depot] for i in cluster]
    single_cap = VEHICLE_CAPACITIES[0] if VEHICLE_CAPACITIES else 999999
    sub_routes = solve_vrp(sub_tm, 1, 0, demands=sub_demands, vehicle_capacities=[single_cap], service_times=sub_service_times, time_windows=sub_time_windows)
    # map back
    mapped = []
    for r in sub_routes:
        mapped_route = []
        for node in r:
            if node == 0:
                mapped_route.append(depot)
            else:
                mapped_route.append(cluster[node - 1])
        mapped.append(mapped_route)
    # return first route (one vehicle per cluster)
    return mapped[0]


def greedy_route_for_cluster(cluster, stops, depot):
    # simple nearest-neighbor greedy route starting/ending at depot
    if not cluster:
        return [depot, depot]
    remaining = set(cluster)
    route = [depot]
    cur = depot
    while remaining:
        best = None
        best_d = None
        for r in remaining:
            d = haversine(stops[cur], stops[r])
            if best is None or d < best_d:
                best = r
                best_d = d
        route.append(best)
        remaining.remove(best)
        cur = best
    route.append(depot)
    return route


def solve_by_clusters(stops, time_matrix, num_vehicles, depot, max_workers: int = None):
    """Partition stops into clusters and solve each cluster in parallel.

    Returns list of routes (one per vehicle). If fewer clusters than vehicles, pads with depot-only routes.
    """
    # determine initial number of sweep clusters:
    k = num_vehicles
    try:
        if CLUSTER_TARGET_SIZE and CLUSTER_TARGET_SIZE > 0:
            # compute k so that average cluster size ~ CLUSTER_TARGET_SIZE (excluding depot)
            k = max(1, math.ceil((len(stops) - 1) / float(CLUSTER_TARGET_SIZE)))
    except Exception:
        k = num_vehicles
    clusters = sweep_partition(stops, k, DEMANDS)
    print(f'[DEBUG] solve_by_clusters: requested num_vehicles={num_vehicles}, cluster_target_size={CLUSTER_TARGET_SIZE}, initial_clusters={len(clusters)}, cluster_max_demand={CLUSTER_MAX_DEMAND}')
    # write cluster debug info to help tuning (sizes and cumulative demand)
    try:
        import pathlib
        import tempfile
        import os as _os
        pathlib.Path('debug').mkdir(parents=True, exist_ok=True)
        cluster_info = []
        for c in clusters:
            total_d = sum(int(DEMANDS[i]) if i < len(DEMANDS) else 1 for i in c)
            # ensure indices are ints
            indices = [int(i) for i in c]
            cluster_info.append({'size': int(len(c)), 'demand': int(total_d), 'indices': indices})
        payload = {'k': int(k), 'clusters': cluster_info}
        # atomic write using temp file then rename
        fd, tmp_path = tempfile.mkstemp(prefix='clusters_debug_', suffix='.json', dir='debug')
        try:
            with os.fdopen(fd, 'w') as fh:
                json.dump(payload, fh, indent=2)
            # ensure rename is atomic on same filesystem
            _os.replace(tmp_path, _os.path.join('debug', 'clusters_debug.json'))
        finally:
            # cleanup if something went wrong
            try:
                if _os.path.exists(tmp_path):
                    _os.remove(tmp_path)
            except Exception:
                pass
        print(f'[DEBUG] Wrote debug/clusters_debug.json with {len(cluster_info)} clusters')
        # also write a manual copy in repo root so CI or editors can read it reliably
        try:
            with open('clusters_debug_manual.json', 'w') as mf:
                json.dump({'k': int(k), 'clusters': cluster_info}, mf, indent=2)
            print('[DEBUG] Wrote clusters_debug_manual.json')
        except Exception as ee:
            print(f'[DEBUG] Failed to write clusters_debug_manual.json: {ee}')
    except Exception as e:
        print(f'[DEBUG] Failed to write clusters_debug.json: {e}')
    # prepare tasks
    # ensure each cluster's total demand does not exceed a single vehicle capacity
    tasks: List[Tuple[List[int], List[Tuple[float,float]], int]] = []
    single_cap = VEHICLE_CAPACITIES[0] if VEHICLE_CAPACITIES else 999999
    for cluster in clusters:
        if not cluster:
            tasks.append((cluster, stops, depot))
            continue
        # split cluster into subclusters by cumulative demand <= single_cap
        cur: List[int] = []
        cur_sum = 0
        for idx in cluster:
            d = DEMANDS[idx] if idx < len(DEMANDS) else 1
            # allow an optional max demand per cluster to further split large geographic clusters
            cap_limit = single_cap
            if CLUSTER_MAX_DEMAND and CLUSTER_MAX_DEMAND > 0:
                cap_limit = min(single_cap, CLUSTER_MAX_DEMAND)
            if cur and cur_sum + d > cap_limit:
                tasks.append((cur, stops, depot))
                cur = [idx]
                cur_sum = d
            else:
                cur.append(idx)
                cur_sum += d
        if cur:
            tasks.append((cur, stops, depot))

    # Use subprocess-based worker per cluster to isolate OR-Tools runtime and avoid
    # inter-process solver issues on Windows. We spawn multiple python processes and pass
    # the cluster payload via stdin as JSON. This keeps resource isolation and avoids
    # pickling large objects.
    import subprocess
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import sys
    # import metrics container from matrix_cache if available
    try:
        from matrix_cache import METRICS as MATRIX_METRICS
    except Exception:
        MATRIX_METRICS = {'ors_calls': 0, 'ors_failures': 0, 'cache_hits': 0}

    def run_cluster_subprocess(task):
        cluster, stops_inner, depot_inner = task
        payload = {'cluster': cluster, 'stops': stops_inner, 'depot': depot_inner}
        try:
            proc = subprocess.run([
                sys.executable,
                __file__,
                '--solve-cluster-stdin'
            ], input=json.dumps(payload).encode('utf-8'), stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=300)
            # write logs for debugging
            import uuid
            tag = uuid.uuid4().hex[:8]
            with open(f'cluster_{tag}.stdout.log', 'wb') as f:
                f.write(proc.stdout)
            with open(f'cluster_{tag}.stderr.log', 'wb') as f:
                f.write(proc.stderr)
            if proc.returncode != 0:
                # write a failure dump for offline inspection
                try:
                    import pathlib
                    pathlib.Path('failures').mkdir(parents=True, exist_ok=True)
                    # attempt to reconstruct subproblem inputs for the cluster
                    sub_stops = [stops_inner[depot_inner]] + [stops_inner[i] for i in cluster]
                    # try to build a local time matrix for the failing cluster (best-effort)
                    try:
                        sub_tm = build_time_matrix(sub_stops)
                    except Exception:
                        sub_tm = []
                    dump = {
                        'cluster': cluster,
                        'depot': depot_inner,
                        'stops': sub_stops,
                        'demands': [0] + [DEMANDS[i] if i < len(DEMANDS) else 1 for i in cluster],
                        'service_times': [0] + [SERVICE_TIMES[i] if i < len(SERVICE_TIMES) else 0 for i in cluster],
                        'time_windows': [TIME_WINDOWS[depot_inner]] + [TIME_WINDOWS[i] if i < len(TIME_WINDOWS) else TIME_WINDOWS[depot_inner] for i in cluster],
                        'time_matrix': sub_tm,
                        'stderr_excerpt': proc.stderr.decode('utf-8', errors='replace')[:8192]
                    }
                    with open(f'failures/cluster_{tag}.json', 'w') as df:
                        json.dump(dump, df, indent=2)
                except Exception as _:
                    pass
                # fallback to greedy route when worker fails
                print(f'Cluster worker failed (see cluster_{tag}.stderr.log), falling back to greedy')
                try:
                    MATRIX_METRICS['greedy_fallbacks'] = MATRIX_METRICS.get('greedy_fallbacks', 0) + 1
                except Exception:
                    pass
                return greedy_route_for_cluster(cluster, stops_inner, depot_inner)
            out = proc.stdout.decode('utf-8')
            res = json.loads(out)
            # if worker returned depot-only, fallback to greedy and write a diagnostic
            if res == [depot_inner, depot_inner]:
                try:
                    import pathlib
                    pathlib.Path('failures').mkdir(parents=True, exist_ok=True)
                    sub_stops = [stops_inner[depot_inner]] + [stops_inner[i] for i in cluster]
                    try:
                        sub_tm = build_time_matrix(sub_stops)
                    except Exception:
                        sub_tm = []
                    dump = {
                        'cluster': cluster,
                        'depot': depot_inner,
                        'stops': sub_stops,
                        'demands': [0] + [DEMANDS[i] if i < len(DEMANDS) else 1 for i in cluster],
                        'service_times': [0] + [SERVICE_TIMES[i] if i < len(SERVICE_TIMES) else 0 for i in cluster],
                        'time_windows': [TIME_WINDOWS[depot_inner]] + [TIME_WINDOWS[i] if i < len(TIME_WINDOWS) else TIME_WINDOWS[depot_inner] for i in cluster],
                        'time_matrix': sub_tm,
                        'note': 'worker returned depot-only route'
                    }
                    with open(f'failures/cluster_{tag}.json', 'w') as df:
                        json.dump(dump, df, indent=2)
                except Exception:
                    pass
                try:
                    MATRIX_METRICS['greedy_fallbacks'] = MATRIX_METRICS.get('greedy_fallbacks', 0) + 1
                except Exception:
                    pass
                return greedy_route_for_cluster(cluster, stops_inner, depot_inner)
            return res
        except Exception as e:
            print(f'Cluster subprocess failed: {e}, falling back to greedy')
            return greedy_route_for_cluster(cluster, stops_inner, depot_inner)

    workers = max_workers or min(len(tasks), max(1, __import__('multiprocessing').cpu_count() - 1))
    tmp = [None] * len(tasks)
    print(f'[DEBUG] solve_by_clusters: total tasks after splitting={len(tasks)}, workers={workers}')
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(run_cluster_subprocess, t): i for i, t in enumerate(tasks)}
        for fut in as_completed(futures):
            idx = futures[fut]
            tmp[idx] = fut.result()
    # tmp now has one route per cluster
    # defensive validation: ensure every task produced a valid route list
    all_routes = []
    for i, r in enumerate(tmp):
        try:
            # Expect a list with at least two entries (depot start/end)
            if isinstance(r, list) and len(r) >= 2:
                # ensure ints
                rout = [int(x) for x in r]
                all_routes.append(rout)
            else:
                # fallback to greedy route for this cluster
                print(f'[WARN] Invalid route for task {i}, using greedy fallback')
                cluster, stops_inner, depot_inner = tasks[i]
                try:
                    MATRIX_METRICS['greedy_fallbacks'] = MATRIX_METRICS.get('greedy_fallbacks', 0) + 1
                except Exception:
                    pass
                all_routes.append(greedy_route_for_cluster(cluster, stops_inner, depot_inner))
        except Exception as e:
            print(f'[ERROR] Exception validating route for task {i}: {e}; using greedy fallback')
            cluster, stops_inner, depot_inner = tasks[i]
            try:
                MATRIX_METRICS['greedy_fallbacks'] = MATRIX_METRICS.get('greedy_fallbacks', 0) + 1
            except Exception:
                pass
            all_routes.append(greedy_route_for_cluster(cluster, stops_inner, depot_inner))
    print(f'[DEBUG] solve_by_clusters: collected routes={len(all_routes)}')
    # write debug log for offline inspection
    try:
        import pathlib
        with open('solve_debug.log', 'w') as df:
            df.write(f'NUM_VEHICLES={num_vehicles}\n')
            df.write(f'initial_clusters={len(clusters)}\n')
            df.write(f'total_tasks={len(tasks)}\n')
            df.write(f'collected_routes={len(all_routes)}\n')
            df.write('sample_routes:\n')
            for i, r in enumerate(all_routes[:10]):
                df.write(f'  {i}: {r}\n')
    except Exception as e:
        print('Could not write solve_debug.log:', e)
    # attempt to write smoke metrics to project root for quick inspection
    try:
        metrics_out = {
            'num_vehicles_requested': num_vehicles,
            'initial_clusters': len(clusters),
            'total_tasks': len(tasks),
            'collected_routes': len(all_routes),
        }
        # include matrix cache metrics if present
        try:
            metrics_out.update({
                'ors_calls': int(MATRIX_METRICS.get('ors_calls', 0)),
                'ors_failures': int(MATRIX_METRICS.get('ors_failures', 0)),
                'cache_hits': int(MATRIX_METRICS.get('cache_hits', 0)),
                'greedy_fallbacks': int(MATRIX_METRICS.get('greedy_fallbacks', 0)),
            })
        except Exception:
            pass
        with open('smoke_metrics.json', 'w') as mf:
            json.dump(metrics_out, mf, indent=2)
    except Exception as e:
        print('Could not write smoke_metrics.json:', e)
    # pad/truncate to num_vehicles
    if len(all_routes) < num_vehicles:
        for _ in range(num_vehicles - len(all_routes)):
            all_routes.append([depot, depot])
    # truncate or pad deterministically
    final_routes = all_routes[:num_vehicles]
    return final_routes


def solve_vrp(time_matrix: List[List[int]], num_vehicles: int, depot: int, demands: List[int] = None, vehicle_capacities: List[int] = None, service_times: List[int] = None, time_windows: List[Tuple[int,int]] = None):
    manager = pywrapcp.RoutingIndexManager(len(time_matrix), num_vehicles, depot)
    routing = pywrapcp.RoutingModel(manager)

    def time_callback(from_index, to_index):
        from_node = manager.IndexToNode(from_index)
        to_node = manager.IndexToNode(to_index)
        # include service time at the from_node (use global SERVICE_TIMES by default)
        if service_times is not None and from_node < len(service_times):
            st = service_times[from_node]
        else:
            st = SERVICE_TIMES[from_node] if 'SERVICE_TIMES' in globals() and from_node < len(SERVICE_TIMES) else 0
        return time_matrix[from_node][to_node] + int(st)

    transit_callback_index = routing.RegisterTransitCallback(time_callback)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_callback_index)

    # Capacity/demand callback
    # Capacity/demand callback: use provided lists if passed, otherwise global ones
    def demand_callback(from_index):
        from_node = manager.IndexToNode(from_index)
        if demands is not None:
            return demands[from_node]
        return DEMANDS[from_node]

    demand_callback_index = routing.RegisterUnaryTransitCallback(demand_callback)
    caps = vehicle_capacities if vehicle_capacities is not None else VEHICLE_CAPACITIES
    # Ensure caps length matches number of vehicles
    if len(caps) != num_vehicles:
        # if a single capacity provided, expand; otherwise trim/pad
        if len(caps) == 1:
            caps = [caps[0]] * num_vehicles
        else:
            caps = (caps + [caps[-1]] * num_vehicles)[:num_vehicles]
    routing.AddDimensionWithVehicleCapacity(
        demand_callback_index,
        0,  # null capacity slack
        caps,  # vehicle maximum capacities
        True,  # start cumul to zero
        'Capacity')

    # Add time dimension to make solver respect durations
    time = 'Time'
    routing.AddDimension(
        transit_callback_index,
        0,  # no slack
        24 * 3600,  # vehicle maximum travel time per route
        True,  # start cumul to zero
        time)

    time_dimension = routing.GetDimensionOrDie(time)
    # minimize the maximum route duration (balance routes) - stronger weight
    time_dimension.SetGlobalSpanCostCoefficient(1000)
    # enforce time windows for each location
    tws = time_windows if time_windows is not None else TIME_WINDOWS
    # normalize time windows to route-relative seconds (start at 0)
    relax_tws = False
    try:
        relax_tws = bool(int(os.environ.get('RELAX_TWS', '0')))
    except Exception:
        relax_tws = os.environ.get('RELAX_TWS', '0').lower() in ('1', 'true', 'yes')
    # if caller requested many vehicles, enable relax
    if not relax_tws:
        try:
            if NUM_VEHICLES >= RELAX_TWS_THRESHOLD:
                relax_tws = True
        except Exception:
            pass

    if relax_tws:
        # skip strict per-stop windows; only set vehicle shift windows below
        pass
    else:
        for node in range(len(time_matrix)):
            index = manager.NodeToIndex(node)
            start, end = tws[node]
            # subtract shift start so windows align with route-level time dimension
            ns = int(max(0, start - SHIFT_START))
            ne = int(max(0, end - SHIFT_START))
            if ns > ne:
                ns, ne = 0, max(ns, ne)
            try:
                time_dimension.CumulVar(index).SetRange(ns, ne)
            except Exception as e:
                # avoid failing the entire solve for a single inconsistent window
                print(f'Warning: could not set time window for node {node}: {e}')
    # enforce vehicle shift windows at start nodes
    for v in range(num_vehicles):
        s_idx = routing.Start(v)
        e_idx = routing.End(v)
        # assume same shift window for all vehicles unless custom provided
        # enforce both start and end of route to fall within the driver shift
        try:
            time_dimension.CumulVar(s_idx).SetRange(0, SHIFT_SECONDS)
        except Exception as e:
            print(f'Warning: could not set shift start for vehicle {v}: {e}')
        try:
            time_dimension.CumulVar(e_idx).SetRange(0, SHIFT_SECONDS)
        except Exception as e:
            print(f'Warning: could not set shift end for vehicle {v}: {e}')

    search_parameters = pywrapcp.DefaultRoutingSearchParameters()
    search_parameters.first_solution_strategy = (
        routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC)
    # use a local search metaheuristic for better quality
    search_parameters.local_search_metaheuristic = (
        routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH)
    # increase time limit for higher-quality solutions
    search_parameters.time_limit.seconds = 180

    solution = routing.SolveWithParameters(search_parameters)
    if not solution:
        raise RuntimeError('No solution found')

    routes = []
    for v in range(num_vehicles):
        index = routing.Start(v)
        route = []
        while not routing.IsEnd(index):
            node = manager.IndexToNode(index)
            route.append(node)
            index = solution.Value(routing.NextVar(index))
        node = manager.IndexToNode(index)
        route.append(node)
        routes.append(route)
    return routes


def save_outputs(routes, stops, time_matrix):
    import csv

    # helper to convert route-relative seconds into wall-clock HH:MM using SHIFT_START
    def seconds_to_hhmm(sec: int) -> str:
        try:
            # route-relative sec + SHIFT_START (seconds from midnight) -> absolute seconds from midnight
            abs_sec = int(sec) + int(SHIFT_START)
            # wrap at 24h
            abs_sec = abs_sec % (24 * 3600)
            hh = abs_sec // 3600
            mm = (abs_sec % 3600) // 60
            return f"{hh:02d}:{mm:02d}"
        except Exception:
            return ''

    # Build enriched routes JSON with per-stop ETA/Depart HH:MM and totals
    enriched = []
    for vid, route in enumerate(routes, start=1):
        seq_rows = []
        total_seconds = 0
        cur_time = 0
        for i in range(len(route) - 1):
            a = route[i]
            b = route[i + 1]
            travel = int(time_matrix[a][b])
            arrival = cur_time + travel
            srv = int(SERVICE_TIMES[b]) if b < len(SERVICE_TIMES) else 0
            depart = arrival + srv
            seq_rows.append({
                'sequence': i + 1,
                'stop': int(b),
                'lat': stops[b][0],
                'lon': stops[b][1],
                'eta_sec': int(arrival),
                'service_sec': int(srv),
                'depart_sec': int(depart),
                'eta_hhmm': seconds_to_hhmm(int(arrival)),
                'depart_hhmm': seconds_to_hhmm(int(depart))
            })
            cur_time = depart
            total_seconds = depart
        enriched.append({'vehicle': vid, 'total_seconds': int(total_seconds), 'total_hours': round(total_seconds / 3600.0, 2), 'stops': seq_rows, 'violates_shift': bool(total_seconds > SHIFT_SECONDS)})
    try:
        with open('routes.json', 'w') as f:
            json.dump(enriched, f, indent=2)
    except Exception as e:
        print('Failed to write routes.json:', e)
    routes_summary = []
    for vid, route in enumerate(routes, start=1):
        rows = []
        total_seconds = 0
        cur_time = 0
        seq = 1
        # we write arrival (eta) at each non-depot stop and include service time
        for i in range(len(route) - 1):
            a = route[i]
            b = route[i + 1]
            travel = int(time_matrix[a][b])
            arrival = cur_time + travel
            srv = 0
            if b < len(SERVICE_TIMES):
                srv = int(SERVICE_TIMES[b])
            depart = arrival + srv
            # accumulate route total
            total_seconds = depart
            rows.append({'sequence': seq, 'stop': int(b), 'lat': stops[b][0], 'lon': stops[b][1], 'eta_sec': int(arrival), 'service_sec': int(srv), 'depart_sec': int(depart), 'eta_hhmm': seconds_to_hhmm(int(arrival)), 'depart_hhmm': seconds_to_hhmm(int(depart))})
            cur_time = depart
            seq += 1
        violates = total_seconds > SHIFT_SECONDS
        # attach violates flag to each row for easy per-stop CSV filtering
        for r in rows:
            r['violates_shift'] = bool(violates)
        csv_name = f'route_vehicle_{vid}.csv'
        with open(csv_name, 'w', newline='') as cf:
            fieldnames = ['sequence', 'stop', 'lat', 'lon', 'eta_sec', 'service_sec', 'depart_sec', 'eta_hhmm', 'depart_hhmm', 'violates_shift']
            writer = csv.DictWriter(cf, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        print(f'Wrote {csv_name} (estimated seconds {total_seconds})')
        routes_summary.append({'vehicle': vid, 'total_seconds': int(total_seconds), 'total_hours': round(total_seconds / 3600.0, 2), 'violates_shift': bool(violates)})

    # write a simple summary CSV for quick review
    summary_name = 'routes_summary.csv'
    try:
        with open(summary_name, 'w', newline='') as sf:
            sfields = ['vehicle', 'total_seconds', 'total_hours', 'violates_shift']
            sw = csv.DictWriter(sf, fieldnames=sfields)
            sw.writeheader()
            sw.writerows(routes_summary)
        print(f'Wrote {summary_name} ({len(routes_summary)} rows)')
    except Exception as e:
        print('Failed to write routes_summary.csv:', e)

    # folium map (optional)
    if _FOLIUM_AVAILABLE and folium is not None:  # type: ignore
        m = folium.Map(location=stops[0], zoom_start=11)
        colors = ['red', 'blue', 'green', 'purple', 'orange', 'darkred']
        for vid, route in enumerate(routes):
            coords = [stops[i] for i in route]
            folium.PolyLine(coords, color=colors[vid % len(colors)], weight=4, opacity=0.7).add_to(m)
            for idx, s in enumerate(route):
                folium.CircleMarker(location=stops[s], radius=4, color=colors[vid % len(colors)], fill=True).add_to(m)
        m.save('routes_map.html')
        print('Saved routes.json and routes_map.html')
    else:
        print('Skipping folium map generation (folium not installed).')


def validate_shifts_and_write(routes, stops, time_matrix):
    """Estimate route start and end times (seconds from route start) using time_matrix
    and write a `shift_validation.json` summarizing any routes that violate the shift length.
    """
    results = []
    for vid, route in enumerate(routes, start=1):
        per_stop = []
        # assume vehicle leaves depot at time 0 (route-relative)
        cur_time = 0
        for i in range(len(route) - 1):
            a = route[i]
            b = route[i + 1]
            travel = int(time_matrix[a][b])
            arrival = cur_time + travel
            # service time at arrival node (0 for depot)
            srv = 0
            if b < len(SERVICE_TIMES):
                srv = SERVICE_TIMES[b]
            depart = arrival + srv
            per_stop.append({'stop': int(b), 'arrival_sec': int(arrival), 'service_sec': int(srv), 'depart_sec': int(depart)})
            cur_time = depart
        est_start = 0
        est_end = int(cur_time)
        violates = est_end > SHIFT_SECONDS or est_start < 0
        results.append({
            'vehicle': vid,
            'est_start_sec': int(est_start),
            'est_end_sec': int(est_end),
            'shift_seconds': int(SHIFT_SECONDS),
            'violates_shift': bool(violates),
            'stops': per_stop
        })
    summary = {'shift_start_seconds': SHIFT_START, 'shift_end_seconds': SHIFT_END, 'vehicles': results}
    # write to project directory explicitly to avoid cwd issues
    try:
        base = os.path.dirname(__file__)
        out_path = os.path.join(base, 'shift_validation.json')
        with open(out_path, 'w') as vf:
            json.dump(summary, vf, indent=2)
        print(f'Wrote shift validation to {out_path}')
    except Exception as e:
        print('Could not write shift_validation.json:', e)
    bad = [r for r in results if r['violates_shift']]
    if bad:
        print(f'Shift validation: {len(bad)} routes exceed shift seconds; see shift_validation.json')
    else:
        print('Shift validation: all routes fit within shift seconds')


def main():
    print('Building time matrix (ORS key present:' , bool(ORS_KEY), ')')
    # startup sentinel to verify this module is executed
    try:
        import pathlib
        import time
        pathlib.Path('debug').mkdir(parents=True, exist_ok=True)
        with open('debug/vrp_started.txt', 'w') as sf:
            sf.write(f'started:{time.time()}\n')
    except Exception:
        pass
    # optionally load input.json to override STOPS/DEMANDS/TIME_WINDOWS
    if os.path.exists('input.json'):
        with open('input.json') as f:
            data = json.load(f)
        global STOPS, DEMANDS, TIME_WINDOWS
        STOPS = [tuple(s) for s in data.get('stops', STOPS)]
        DEMANDS = data.get('demands', DEMANDS)
        TIME_WINDOWS = [tuple(tw) for tw in data.get('time_windows', TIME_WINDOWS)]
        # optional: num_vehicles override
        global NUM_VEHICLES
        if 'num_vehicles' in data:
            NUM_VEHICLES = int(data['num_vehicles'])
        # optional: shift override in seconds from midnight
        global SHIFT_START, SHIFT_END, SHIFT_SECONDS
        try:
            if 'shift_start_seconds' in data:
                SHIFT_START = int(data['shift_start_seconds'])
            if 'shift_end_seconds' in data:
                SHIFT_END = int(data['shift_end_seconds'])
            SHIFT_SECONDS = max(0, int(SHIFT_END - SHIFT_START))
        except Exception:
            print('Warning: invalid shift override in input.json; using defaults')
    tm = build_time_matrix(STOPS)
    # compute partitions and write debug before solving
    k = NUM_VEHICLES
    if CLUSTER_TARGET_SIZE and CLUSTER_TARGET_SIZE > 0:
        try:
            k = max(1, math.ceil((len(STOPS) - 1) / float(CLUSTER_TARGET_SIZE)))
        except Exception:
            k = NUM_VEHICLES
    clusters = sweep_partition(STOPS, k, DEMANDS)
    try:
        write_clusters_manual(clusters, k)
    except Exception:
        pass
    # Try cluster-based solve for better balancing
    routes = solve_by_clusters(STOPS, tm, NUM_VEHICLES, DEPOT)
    save_outputs(routes, STOPS, tm)
    # run post-run shift validator
    try:
        validate_shifts_and_write(routes, STOPS, tm)
    except Exception as e:
        print('Shift validation failed:', e)


if __name__ == '__main__':
    import sys
    # fast emitter mode
    if '--emit-clusters-only' in sys.argv:
        # load input.json if present
        if os.path.exists('input.json'):
            with open('input.json') as f:
                data = json.load(f)
            STOPS = [tuple(s) for s in data.get('stops', STOPS)]
            DEMANDS = data.get('demands', DEMANDS)
            if 'num_vehicles' in data:
                NUM_VEHICLES = int(data['num_vehicles'])
        k = NUM_VEHICLES
        if CLUSTER_TARGET_SIZE and CLUSTER_TARGET_SIZE > 0:
            try:
                k = max(1, math.ceil((len(STOPS) - 1) / float(CLUSTER_TARGET_SIZE)))
            except Exception:
                k = NUM_VEHICLES
        clusters = sweep_partition(STOPS, k, DEMANDS)
        write_clusters_manual(clusters, k)
        sys.exit(0)
    if '--solve-cluster-stdin' in sys.argv:
        # read JSON payload from stdin {cluster, stops, depot}
        import json
        payload = json.load(sys.stdin)
        cluster = payload['cluster']
        stops = [tuple(s) for s in payload['stops']]
        depot = int(payload['depot'])
        # build subproblem
        if not cluster:
            print(json.dumps([depot, depot]))
            sys.exit(0)
        sub_stops = [stops[depot]] + [stops[i] for i in cluster]
        sub_tm = build_time_matrix(sub_stops)
        sub_demands = [0] + [DEMANDS[i] if i < len(DEMANDS) else 1 for i in cluster]
        sub_service_times = [0] + [SERVICE_TIMES[i] if i < len(SERVICE_TIMES) else 0 for i in cluster]
        sub_time_windows = [TIME_WINDOWS[depot]] + [TIME_WINDOWS[i] if i < len(TIME_WINDOWS) else TIME_WINDOWS[depot] for i in cluster]
        single_cap = VEHICLE_CAPACITIES[0] if VEHICLE_CAPACITIES else 999999
        sub_routes = solve_vrp(sub_tm, 1, 0, demands=sub_demands, vehicle_capacities=[single_cap], service_times=sub_service_times, time_windows=sub_time_windows)
        mapped = []
        for r in sub_routes:
            mapped_route = []
            for node in r:
                if node == 0:
                    mapped_route.append(depot)
                else:
                    mapped_route.append(cluster[node - 1])
            mapped.append(mapped_route)
        # print first route as JSON
        print(json.dumps(mapped[0]))
        sys.exit(0)
    else:
        main()
