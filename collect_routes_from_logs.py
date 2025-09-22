import glob
import json
from pathlib import Path

ROOT = Path(__file__).parent

def main():
    routes = []
    files = sorted(glob.glob(str(ROOT / 'cluster_*.stdout.log')))
    for f in files:
        try:
            txt = Path(f).read_text().strip()
            if not txt:
                continue
            # attempt to parse as JSON array
            arr = json.loads(txt)
            routes.append(arr)
        except Exception:
            # try to extract a JSON-looking substring
            try:
                s = txt[txt.find('['):txt.rfind(']')+1]
                arr = json.loads(s)
                routes.append(arr)
            except Exception:
                continue
    out = {'count': len(routes), 'sample': routes[:20]}
    Path(ROOT / 'routes_from_logs.json').write_text(json.dumps(out, indent=2))
    print('Wrote routes_from_logs.json with', out['count'], 'routes')

if __name__ == '__main__':
    main()
