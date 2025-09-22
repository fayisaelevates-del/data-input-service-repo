import os
import json
from pathlib import Path

ROOT = Path(__file__).parent

def main():
    inp = ROOT / 'input.json'
    if not inp.exists():
        raise SystemExit('input.json not found; run smoke_200.py first')
    data = json.loads(inp.read_text())
    stops = [tuple(s) for s in data.get('stops', [])]
    num_vehicles = int(data.get('num_vehicles', 2))
    # ensure relax flag
    os.environ['RELAX_TWS'] = os.environ.get('RELAX_TWS', '1')

    # import solver helpers
    import vrp_prototype as vp

    print('Debug driver: building time matrix')
    tm = vp.build_time_matrix(stops)
    print('Debug driver: calling solve_by_clusters')
    routes = vp.solve_by_clusters(stops, tm, num_vehicles, 0)

    # write debug
    with open(ROOT / 'solve_debug.log', 'w') as df:
        df.write(f'NUM_VEHICLES={num_vehicles}\n')
        df.write(f'stops={len(stops)}\n')
        df.write(f'collected_routes={len(routes)}\n')
        for i, r in enumerate(routes[:50]):
            df.write(f'{i}: {r}\n')

    # write routes_debug.json
    out = [{'vehicle': i+1, 'stops': r} for i, r in enumerate(routes)]
    with open(ROOT / 'routes_debug.json', 'w') as jf:
        json.dump(out, jf, indent=2)
    print('Wrote routes_debug.json and solve_debug.log')

if __name__ == '__main__':
    main()
