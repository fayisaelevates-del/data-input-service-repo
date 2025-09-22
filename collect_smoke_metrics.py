import json

def main():
    with open('shift_validation.json') as f:
        d = json.load(f)
    vs = d.get('vehicles', [])
    n = len(vs)
    viol = sum(1 for v in vs if v.get('violates_shift'))
    max_end = max((v.get('est_end_sec', 0) for v in vs), default=0)
    avg_end = sum((v.get('est_end_sec', 0) for v in vs), 0) / (n or 1)
    shift_seconds = vs[0].get('shift_seconds') if vs else d.get('shift_end_seconds') - d.get('shift_start_seconds')
    near = [ {'vehicle': v['vehicle'], 'est_end_sec': v['est_end_sec']} for v in vs if v.get('est_end_sec',0) > 0.9 * (shift_seconds or 1) ]
    out = {
        'vehicles': n,
        'violations': viol,
        'max_end_sec': max_end,
        'avg_end_sec': avg_end,
        'shift_seconds': shift_seconds,
        'near_shift_count': len(near),
        'near_shift_vehicles': near,
    }
    with open('smoke_metrics.json', 'w') as f:
        json.dump(out, f, indent=2)
    print('wrote smoke_metrics.json')

if __name__ == '__main__':
    main()
